# 帧方向与镜像契约

本文件是 NveEffectKit 3.16.1 实时帧链的自包含方向基线。接入或修改相机、预览、录制、RTC、单图、方向、镜像、摄像头切换时必须执行；只使用本契约与客户工程事实，不得把角度映射交给经验推断。

## 目录

- [先建立唯一所有权](#先建立唯一所有权)
- [标准实时相机链](#标准实时相机链)
- [SDK mirror 全零兼容分支](#sdk-mirror-全零兼容分支)
- [字段语义与禁止组合](#字段语义与禁止组合)
- [摄像头切换](#摄像头切换)
- [非标准输入](#非标准输入)
- [方向故障修复](#方向故障修复)
- [验收](#验收)

## 先建立唯一所有权

修改代码前，从客户工程源码填写以下账本。每行只能有一个执行者；未知项不得用猜测补齐。

| 维度 | 必须记录的事实 |
| --- | --- |
| 输入来源 | `AVCaptureVideoDataOutput`、文件/单图、RTC callback 或 OpenGL texture |
| 输入像素方向 | 上游是否已经把 buffer 旋转到产品展示方向；证据是现有连接配置、转换代码或供应方契约 |
| SDK 方向 owner | 是否确有已验证契约要求设置 `imageOrientation`/`displayRotation` |
| 输出像素方向 | NVE 输出是否保持输入方向；通过同版本基线或一帧尺寸/非对称画面验证 |
| 预览方向 owner | display layer/view 是否已有 rotation transform |
| 镜像 owner | NVE 输入、预览消费者、录制消费者三者中谁执行横向镜像 |
| 产品输出 | 前摄预览和成片分别要求镜像或非镜像 |
| 切换状态 | 每帧 camera position、generation 在何处快照 |

无法从客户现有代码、公共头文件或用户明确提供的资料证明某项时，保留现有语义并把该项列为验证阻塞；禁止试填 `90/180/270`、交换宽高或叠加 view transform。

## 标准实时相机链

`AVCaptureVideoDataOutput → buffer-buffer → AVSampleBufferDisplayLayer` 固定使用以下低自由度基线：

1. 在帧流开始前给 video output connection 设置产品目标方向。竖屏应用设置 `.portrait`。
2. NVE 是标准链的镜像 owner：关闭 connection 的自动镜像并显式设置 `isVideoMirrored = false`，避免 capture 先镜像、NVE 再镜像。
3. 每次更换 camera input 或重建 capture session 后，在提交配置期间重新应用同一 connection 方向和 mirroring-off 配置。
4. 每帧在串行 render queue 获取该帧的 front/back 快照。
5. 创建 `NveImageBuffer`，只设置 `pixelBuffer` 和 `mirror = isFrontCamera`；保持 `imageOrientation`、`displayRotation` 的 SDK 默认值。
6. 设置 `config.isFromFrontCamera = isFrontCamera`；它只描述来源，不承担显示旋转或镜像。
7. NVE 输出在回收前复制为调用方拥有的 buffer。
8. 用 `AVSampleBufferDisplayLayer` 直接 enqueue presentation-ready 输出；display layer/view 不旋转、不交换 bounds、不再次镜像。

Swift 使用 `NVEFrameGeometry.upstreamOriented(mirror:)`，Objective-C 使用 `NVEFrameGeometryMakeUpstreamOriented`。这两个命名表示上游 capture connection 已经完成方向归一化，并会刻意跳过 SDK 的方向字段。

这是首次接入的默认策略，不是覆盖已验证客户实现的迁移命令。客户工程已有单一 mirror owner 且完成前后摄与录制验收时保留原策略。

## SDK mirror 全零兼容分支

只有 `buffer-buffer` 真机链同时满足以下证据，才把 mirror owner 从 NVE 改为 capture connection：

1. 后摄切前摄后，源 buffer 的尺寸、OSType、plane 数正确，NV12 的 Y/UV 稀疏采样不是全零。
2. `renderEffect` 返回 `noError` 和非空 pixel buffer，但启用 `image.mirror` 时输出 Y/UV 稀疏采样全零；等待 GPU 完成后仍不恢复。
3. 在同一输入格式和相机状态下关闭 `image.mirror`，下一有效帧输出恢复非零。

稀疏采样只在诊断构建中执行，不记录图像内容，不作为每帧生产检查。有效黑场的 video-range NV12 通常仍有非零 luma/chroma；不能只凭画面观感认定“全零”。

证据成立后使用 `captureMirrored` 兼容策略：

1. 关闭 connection 自动镜像。
2. 后摄设置 `connection.isVideoMirrored = false`，前摄设置 `true`；每次切换 input 后重新应用。
3. 所有帧设置 `image.mirror = false`。
4. 仍设置 `config.isFromFrontCamera = isFrontCamera`；该字段只描述来源。
5. preview 不再 transform；它直接消费 capture 已镜像、NVE 已处理的 presentation-ready 输出。
6. 录制语义随 capture 镜像发生变化；若产品要求前摄成片非镜像，为 recording-owned frame 单独反镜像。

Swift 使用 `NVEFrameGeometry.captureMirrored`，Objective-C 使用 `NVEFrameGeometryMakeCaptureMirrored`。策略在一次 session/相机代际内固定，不能检测到一帧异常就静默在 NVE-owned 与 capture-owned 之间切换。没有上述 A/B 证据时继续使用默认策略，并把真机方向验收标为阻塞。

如果产品要求“前摄预览镜像、录制非镜像”，不能把标准链的一份像素同时交给两个语义不同的消费者。为预览和录制分别建立调用方拥有的输出，在消费者边界执行差异化镜像；不得在 display view 上补偿一份已经由 `image.mirror` 镜像的输出。

## 字段语义与禁止组合

| 字段/操作 | 默认 NVE-owned | 已取证 capture-owned |
| --- | --- | --- |
| `connection.videoOrientation` 或 iOS 17+ 等价 rotation angle | 唯一旋转 owner；开始和切摄像头后设置 | 相同 |
| `connection.isVideoMirrored` | 显式 `false`；关闭自动镜像 | 前摄 `true`、后摄 `false`；关闭自动镜像 |
| `image.mirror` | 前摄 `true`、后摄 `false` | 始终 `false` |
| `config.isFromFrontCamera` | 与本帧 camera position 一致 | 相同，不能省略 |
| `image.imageOrientation` | 不赋值 | 不赋值 |
| `image.displayRotation` | 不赋值 | 不赋值 |
| preview rotation/mirror transform | 禁止 | 禁止 |
| width/height 交换 | 禁止作为方向修复 | 禁止作为方向修复 |

以下组合视为接入错误，不是可接受的“多重保险”：

- capture connection 已设置方向，同时又把 `.portrait` 固定映射为 `displayRotation = 90`；
- SDK 设置 `displayRotation`，preview layer/view 又执行 rotation transform；
- capture connection 已镜像，`image.mirror` 又可能为 `true`；
- `image.mirror = isFrontCamera`，preview view 又按同一个 front-camera 状态执行 `scaleX = -1`；
- 为修复显示方向而修改 texture layout；layout 上下翻转不是相机旋转；
- 仅看 buffer 宽高就推断旋转角；尺寸只能作为诊断证据，不能定义坐标契约；
- 用预览 transform 掩盖人脸检测/道具方向错误；检测输入必须先正确。

## 摄像头切换

固定顺序：

```text
transitioning = true
→ 丢弃新进入的帧
→ beginConfiguration / 替换 input
→ 重新设置 video connection 方向和 capture mirroring 策略
→ commitConfiguration
→ preview generation + 1，清掉 pending 旧帧
→ 在同一 render queue 排到旧 callback 之后提交新 camera position
→ transitioning = false
```

默认链由 NVE 烘焙镜像，兼容链由 capture 烘焙镜像；两者的异步 preview frame 都只需携带 generation，不能在 drain 时重新读取全局 camera position，也不应再次切换 view transform。只有客户已有并已验证“preview consumer 单独镜像”的非标准链，preview frame 才携带自己的 mirror 快照，并在首个新代际帧到达时原子更新 transform 与 enqueue。

## 非标准输入

文件、单图、RTC 或未由 capture connection 归一化的原始 buffer 必须显式选择一个旋转 owner：

1. 优先复用客户现有、已经验证的上游归一化；
2. 上游不能改且客户 SDK 契约明确要求 NVE 元数据时，使用 `explicitSDKMetadata`，同时记录 `imageOrientation` 和 `displayRotation` 的来源；
3. 使用 SDK 显式元数据后，下游预览/编码不再旋转；
4. 没有客户代码、公共头文件或用户资料能证明角度含义时保持阻塞，不按设备方向、EXIF 名称或屏幕宽高猜角度。

`explicitSDKMetadata` 是例外路径，不得作为标准相机链的默认值。代码评审和交付报告必须写出使用它的证据。

texture 模式另外记录 `textureLayout`；它只描述纹理上下方向，不能替代 rotation/mirror。

## 方向故障修复

收到“横向、倒置、左右颠倒、道具漂移”等反馈时，任务固定归类为 `repair`，先取证再改代码：

1. 记录 capture connection 的方向/rotation angle 和 mirroring 设置。
2. 记录输入与 NVE 输出的宽、高、pixel format；不记录帧内容。
3. 记录本帧 camera position、`image.mirror`、`isFromFrontCamera`，以及是否赋值 SDK 方向字段。
4. 记录 preview layer/view 的 bounds、affine/3D transform 和 video gravity。
5. 把事实填回方向账本，标出重复 owner 或未知 owner。
6. 一次只移除或修正一个错误 owner，重新验证；不得连续尝试角度常量。

黑屏/绿屏还要在 SDK output 回收前比较源与输出的尺寸、OSType、plane 数和诊断性 Y/UV 稀疏采样。若只在 SDK mirror 开启时得到全零输出，按“SDK mirror 全零兼容分支”做一次 A/B 隔离；不能先改 preview、色彩矩阵或复制器。

若无法运行真机，仍可删除静态可证明的重复旋转/镜像，但必须把真实画面方向标为“未执行”，不能声称已修复或完整通过。

## 验收

实时相机首次接入至少覆盖：

- 后摄竖屏：带文字或非对称物体方向正常；
- 前摄竖屏：文字/左右关系符合产品镜像规则；
- 前→后→前：没有旧帧短暂套用新镜像；
- 后→前时源与 NVE 输出均有有效非零 plane 数据；使用 capture-owned 时保留触发该策略的 A/B 诊断摘要；
- 面板展开、slider 连续变化：preview transform 不变化；
- 项目声明支持横屏时，对每个支持方向分别执行；
- 有录制时，预览和成片分别按产品契约验证。

没有可控真机或可靠相机输入时，这一层是阻塞项。可以交付已编译代码，但结果必须写成“方向/镜像未验收”，不得写“完整接入完成”或“方向已修复”。
