# 渲染链路

## 目录

- [核心类型](#核心类型)
- [模式选择](#模式选择)
- [CVPixelBuffer 输入](#cvpixelbuffer-输入)
- [纹理输入输出](#纹理输入输出)
- [方向和镜像](#方向和镜像)
- [时间戳](#时间戳)
- [输出所有权](#输出所有权)
- [线程与上下文](#线程与上下文)
- [单图处理](#单图处理)
- [错误处理](#错误处理)

## 核心类型

`NveRenderInput`：

- `texture`：`NveTexture`，包含 OpenGL texture ID、尺寸和 layout。
- `imageBuffer`：`NveImageBuffer`，包含 `CVPixelBufferRef`、镜像和方向信息；公共头文件注明它也用于人脸检测。
- `config`：`NveRenderConfig`，构造 input 后确认它非空再设置。
- `renderTimestamp`：可选调用方时间戳。公共头文件未声明单位；没有客户 SDK 的明确单位/时基契约时保持默认值，不要猜测或直接传 `CMTime.value`。

`NveRenderConfig`：

- `renderMode`：三种输入输出组合。
- `outputTextureLayout`：`bottom_up` 或 `up_down`。
- `outputFormatType`：`none`、`bgra`、`nv12`、`yuv420`；`none` 表示尽量保持输入格式。
- `overlayInputBuffer`：请求把结果覆盖到输入 buffer。开启前必须确认输入 buffer 可写、生命周期独占且下游接受原地修改。
- `isFromFrontCamera`：图像来源是否为前置摄像头。
- `autoMotion`：仅在明确知道素材需要自动 motion 行为时设置；不要作为默认修复方向问题的开关。

`NveRenderOutput`：

- `errorCode`：渲染状态。
- `texture`：纹理输出模式使用。
- `pixelBuffer`：buffer 输出模式使用。
- 输出资源由 NveEffectKit 管理，消费结束后交回 `recycleOutput`。

## 模式选择

| 标识 | SDK 枚举 | 必填输入 | 预期输出 | 推荐场景 |
| --- | --- | --- | --- | --- |
| `buffer-buffer` | `NveRenderMode_buffer_buffer` | `imageBuffer.pixelBuffer` | `output.pixelBuffer` | AVFoundation、编码器、RTC/直播 SDK 继续消费 buffer |
| `buffer-texture` | `NveRenderMode_buffer_texture` | `imageBuffer.pixelBuffer` | `output.texture` | 输入来自相机，下游已有 OpenGL 预览/滤镜链 |
| `texture-texture` | `NveRenderMode_texture_texture` | `texture` | `output.texture` | 上游已经提供 OpenGL texture |

不要根据 demo 的默认值决定模式。先从现有下游需要的数据类型反推，避免 buffer 与 GPU 间不必要的上传/下载。

NveEffectKit 公共 API 是 OpenGL texture API，不是 Metal API。客户只有 `MTLTexture` 时，优先走 `CVPixelBuffer` 模式或沿用客户已有的显式 Metal/OpenGL bridge；不能把 Metal texture 标识强转成 `GLuint`。

## CVPixelBuffer 输入

标准实时相机 `AVCaptureVideoDataOutput → buffer-buffer` 的 Objective-C 同步渲染骨架如下。前提是 video output connection 已按 [帧方向与镜像契约](frame-geometry-contract.md) 设置目标方向：

```objective-c
CVPixelBufferRef pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
if (!pixelBuffer) { return; }

NveRenderInput *input = [[NveRenderInput alloc] init];
NveImageBuffer *image = [[NveImageBuffer alloc] init];
image.pixelBuffer = pixelBuffer;
image.mirror = isFrontCamera;
// capture connection 已归一化方向；不要再赋值 imageOrientation/displayRotation。
input.imageBuffer = image;
NveRenderConfig *config = [[NveRenderConfig alloc] init];
config.renderMode = NveRenderMode_buffer_buffer;
config.isFromFrontCamera = isFrontCamera;
config.outputFormatType = NvePixelFormatType_none;
input.config = config;
// 仅在客户 SDK 明确约定单位和时基时设置：
// input.renderTimestamp = convertToVendorTimebase(sampleBufferTimestamp);

NveRenderOutput *result = [kit renderEffect:input];
if (!result) { return; }
@try {
    if (result.errorCode != NveRenderError_noError || !result.pixelBuffer) {
        return;
    }
    consumeSynchronously(result.pixelBuffer);
} @finally {
    [kit recycleOutput:result];
}
```

实际工程不必使用 `@try/@finally`，但必须用单一 cleanup 路径保证恰好回收一次。不要在 `renderEffect` 调用前长期持有 `CMSampleBuffer`；`NveImageBuffer.pixelBuffer` 是 assign 语义，渲染期间原 buffer 必须仍有效。

输入格式不被支持时，先记录 `CVPixelBufferGetPixelFormatType`。只有确有需要时使用 `convertI420toNV12` 或客户已有转换器，避免每帧无条件转换。

## 纹理输入输出

`texture-texture` 输入至少设置：

```objective-c
NveRenderInput *input = [[NveRenderInput alloc] init];
NveTexture *texture = [[NveTexture alloc] init];
texture.textureId = inputTextureId;
texture.size = inputSize;
texture.textureLayout = inputLayout;
input.texture = texture;
NveRenderConfig *config = [[NveRenderConfig alloc] init];
config.renderMode = NveRenderMode_texture_texture;
config.outputTextureLayout = requiredOutputLayout;
input.config = config;
```

规则：

- `textureId` 必须是在当前 EAGLContext 或共享组中有效的 2D OpenGL texture。
- 尺寸必须与实际 texture 一致，不能使用 view 尺寸代替视频纹理尺寸。
- 在使用 texture 前把创建/共享它的 EAGLContext 设为当前 context，并检查 `setCurrentContext:` 返回值；失败时不进入渲染。
- 需要人脸效果时，确认客户 SDK 对 texture 模式的人脸检测要求。若上游同时有与该 texture 同步的 pixel buffer，可按供应方约定提供 `imageBuffer`；不要用不同帧的 buffer 参与检测。
- `buffer-texture` 的上传由 SDK 完成，但仍要在有效的 OpenGL context 上调用。
- `uploadPixelBufferToTexture` 和 `downloadPixelBufferFromTexture` 是显式转换工具，不要与 `renderEffect` 的内置模式重复转换。

## 方向和镜像

方向和镜像严格执行 [帧方向与镜像契约](frame-geometry-contract.md)，不在调用点自由组合字段。

- 默认实时相机链由 capture connection 负责旋转、NVE 负责镜像；NVE 设置本帧 `mirror` 和 `isFromFrontCamera`，preview 直接显示 presentation-ready 输出。
- 保留客户工程已经真机验证的单一 mirror owner。首次接入默认使用 NVE-owned mirror；只有源帧正常、NVE mirror 输出全零、关闭 NVE mirror 后恢复的真机 A/B 证据齐全时，才使用 `captureMirrored`。
- `captureMirrored` 由 connection 对前摄设 `isVideoMirrored = true`，NVE 始终 `image.mirror = false`，preview 不再镜像；`config.isFromFrontCamera` 仍跟随本帧 camera position。
- `imageOrientation`/`displayRotation` 只属于有独立证据的 `explicitSDKMetadata` 例外路径。不得把 `.portrait` 经验映射为 `90`。
- 前摄预览与录制需要不同镜像语义时，在各自消费者边界建立独立 owned frame；不能用同一原地覆盖 buffer 满足两种输出。
- texture layout 上下翻转与相机旋转、横向镜像是三个独立维度。
- 方向或绿屏故障先记录 capture、输入/NVE 输出尺寸与 plane 有效性、SDK 字段和 preview transform，再改一个 owner；禁止通过交换 bounds、叠加 view rotation 或逐帧自动回退试错。

至少用非对称画面和带文字的物体分别验证前/后摄像头、竖屏和项目支持的横屏方向。没有真机证据时必须报告未验收。

## 时间戳

- 默认不设置 `renderTimestamp`。只有供应方文档/技术支持对客户版本明确给出单位和时基时才接入。
- 设置时使用与现有媒体管线一致、单调递增的时间基准，并把唯一转换集中在 adapter 中。
- 公共 NveEffectKit 头文件只暴露 `int64_t renderTimestamp`，没有声明单位。不得从未声明时基的整数时间字段或任意 `CMTime.value` 缩放推断其单位。
- 丢帧时不要倒退时间戳。重建会话时是否从零开始按下游和素材语义决定。

## 输出所有权

核心不变量：每个非空 `NveRenderOutput` 恰好回收一次。

同步消费：

```text
render → validate → preview/encode/copy → recycle
```

异步消费必须选择一种明确策略：

1. 下游 API 在调用内复制或 retain 资源，并且其文档保证调用返回后可回收。
2. 调用方把输出复制到自有 buffer/texture，再立即回收 NVE 输出。
3. 将 output lease 传给异步消费者，由唯一 completion owner 在消费完成后回收。

不能先 `recycleOutput` 再把 `output.pixelBuffer` 或 `output.texture` 交给异步队列。也不能因为渲染错误就跳过回收。

若启用 `overlayInputBuffer`，输出可能与输入共享存储；仍按 API 返回结果回收 output，但不要释放不属于调用方的原始 capture buffer。

## 线程与上下文

- 使用稳定串行帧队列调用 render，防止同一单例上的帧并发重入。
- 在帧队列外完成授权、模型文件查找、素材安装、JSON 解析、图片加载和效果对象构建。
- texture 模式在每次队列切换后确认 EAGLContext current；不要假设主线程 context 会自动传播。
- 销毁时先停止帧源，再 barrier/flush 渲染队列，最后销毁单例和 GL 资源。

涉及 UI 高频状态、异步输出、录制/RTC 分流或摄像头切换时，直接执行 [实时效果状态与输出消费规范](realtime-state-and-output.md)。该规范统一适用于美颜、美妆、滤镜、道具、分割等效果模块，以及预览、录制、RTC/直播等输出消费者，不在各功能章节复制 coordinator。同步 OpenGL/直接预览链没有异步消费者时不强行增加 mailbox。

## 单图处理

- 将 `UIImage`/文件解码为受支持的 `CVPixelBuffer` 或 OpenGL texture，然后复用同一 render adapter。
- 保留原图方向和色彩格式；不要用屏幕尺寸缩放图片。
- 单图也需要授权和相关模型。
- 批处理多图时复用单例、模型和已安装 package；逐图只创建 input/output，并及时回收。
- 输出保存前明确颜色空间、alpha 和方向，避免“特效正确但导出翻转/偏色”。

## 错误处理

| 错误 | 含义 | 首查项 |
| --- | --- | --- |
| `NveRenderError_noError` | 成功 | 继续检查对应输出字段非空 |
| `NveRenderError_unknown` | 未分类失败 | 授权、模型、SDK 配对、线程/context |
| `NveRenderError_invalidTexture` | texture 无效 | context、texture ID、尺寸、目标平台 |
| `NveRenderError_invalidPixelFormat` | buffer 格式不支持 | OSType、转换路径、输出格式 |
| `NveRenderError_inputParam` | 输入配置错误 | renderMode 与 input 字段、尺寸、方向配置 |

记录错误码、render mode、非敏感的像素格式/尺寸/方向和 SDK 版本；不要记录帧内容、授权内容或客户素材证书。
