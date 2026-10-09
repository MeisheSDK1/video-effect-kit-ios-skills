# 资源、性能与排障

## 目录

- [3.16.1 模型映射](#3161-模型映射)
- [资源定位](#资源定位)
- [SDK 与平台兼容](#sdk-与平台兼容)
- [素材安装错误](#素材安装错误)
- [常见故障](#常见故障)
- [性能策略](#性能策略)
- [安全与日志](#安全与日志)
- [资料中的已知偏差](#资料中的已知偏差)
- [升级审计](#升级审计)

## 3.16.1 模型映射

枚举、文件名、功能、具体美颜控件和条件素材能力只从 [baseline-3.16.1.json](baseline-3.16.1.json) 的 `models`、`feature_model_requirements`、`beauty_control_requirements` 和 `asset_capability_models` 查询，不在文档中复制清单。该基线只适用于当前 3.16.1.2 实际资源；背景模型为 small/medium 二选一，`unmapped_resource_files` 中的 skysegment 不参与 NveEffectKit 初始化。

供应方审计只读取基线声明的官方初始化源，并结构化比较 Demo 的“枚举 → 文件”初始化映射；文件仅存在、枚举单独出现或二者绑定错误都不算接入完成。

旧 `makeup2` 类型在 3.13+ 已废弃，使用 `faceCommon`。不要同时使用旧类型和新类型以“提高兼容性”。

## 资源定位

资源可能位于主 app bundle、动态 framework resource bundle、CocoaPods resource bundle 或客户资源管理层。

规则：

- 先复用客户已有资源定位器。
- framework/pod 内资源使用稳定 anchor class 定位其 bundle；不要默认 `NSBundle.mainBundle`。
- 输入给 NVE 前检查文件存在、是普通文件/目录、扩展名正确且可读。
- 源码树中的文件存在不代表能在设备运行时访问。本地随包资源必须属于目标的资源构建阶段或由客户既有构建规则复制；编译后在目标 `.app`/资源 bundle 中验证实际解析的相对路径。
- 组合妆容需要解压目录；模型和单项效果需要具体文件。
- 不把绝对开发机路径存入源码、plist 或缓存。缓存应使用相对资源标识，启动时重新解析 URL。
- 不扫描或输出 `.lic` 文件内容，只验证路径存在。
- package 与 package license 必须来自同一供应方交付，不能按 UUID 从其他版本目录拼接证书。

客户使用内部 bundle 时，模板中的 `resourceRoot` 必须作为注入参数，而不是写死 `model.bundle`。只有客户资源确实保持 demo 结构时，才按对应 bundle 名查找。

对于本地素材滤镜，至少验证所选 `.videofx`、配套 `.lic` 及其目录清单（若项目使用清单）进入同一个运行时可解析资源域。封面缺失可以降级为占位图，但 package、证书或清单缺失必须阻止选择。远程素材不强制进入 `.app`，但启动/UI smoke 必须证明下载完成后的缓存 URL 可读且没有使用开发机绝对路径。

## SDK 与平台兼容

3.16.1 基线事实：

- NveEffectKit 的 `MinimumOSVersion` 是 iOS 12.0。
- 当前提供的 NveEffectKit 只声明 `iPhoneOS`，不能据此在模拟器运行。
- demo Podfile 声明 iOS 11.0，与 framework 元数据冲突；有效最低版本应取更高值。
- NveEffectKit 会链接 `NvEffectSdkCore` 或 `NvStreamingSdkCore` 的特定变体。类名/头文件相似不代表二进制 ABI 兼容。

检查顺序：

1. 读取客户 NveEffectKit `Info.plist` 的 MinimumOSVersion 和 SupportedPlatforms。
2. 识别客户 core SDK 名称和版本。
3. 检查项目是否同时链接两个 core 变体或重复的 NveEffectKit。
4. 检查 device/simulator、arm64 等目标 slice。
5. 检查 Link Binary With Libraries、Embed & Sign、framework search path、`-ObjC`。
6. 版本或配对不明时停止，要求客户从供应方取得匹配交付包。

不要通过复制头文件、修改 modulemap、删除 undefined symbol 或关闭架构来掩盖 SDK 配对错误。

## 素材安装错误

`NvsAssetPackageManagerError`：

| 错误 | 处理 |
| --- | --- |
| `NoError` | 成功，缓存返回 ID |
| `AlreadyInstalled` | 成功；必要时从 manager 查询 ID |
| `Name` | 检查文件名/包结构，不能只改显示名 |
| `WorkingInProgress` | 合并并发请求，等待当前安装完成；不要循环重试 |
| `NotInstalled` | 检查是否把查询/升级路径当安装路径 |
| `ImproperStatus` | 检查并发、升级状态和 SDK 生命周期 |
| `Decompression` | 检查包完整性、目录权限和磁盘空间 |
| `InvalidPackage` | 检查包损坏或版本不支持 |
| `AssetType` | 检查扩展名到 `NvsAssetPackageType` 的映射 |
| `Permission` | 检查素材 `.lic` 是否匹配，禁止输出证书内容 |
| `MetaContent` | 检查包元数据与 SDK 版本 |
| `SdkVersion` | 使用与包匹配的 SDK/新版素材 |
| `UpgradeVersion` | 检查降级/升级顺序，不覆盖客户缓存 |
| `IO` | 检查文件可读、磁盘和沙盒路径 |
| `Resource` | 检查包内资源完整性 |

`.animatedsticker` 使用 `NvsAssetPackageType_AnimatedSticker`，由匹配 core SDK 创建 effect 后加入 `customEffectArray`；不要误按 ARScene 安装。

安装缓存 key 至少包含素材稳定标识、素材类型和 SDK 版本。客户替换同 UUID 的版本时应使缓存失效。

## 常见故障

### 授权失败或始终无效果

按顺序检查：

1. `verifySdkLicenseFile` 是否在第一次 `shareInstance` 之前调用。
2. 授权是否绑定当前 target 的 Bundle Identifier，而非 demo 或另一个环境。
3. 是否有某个 view model/全局对象在授权前间接访问单例。
4. SDK 变体是否配对。
5. 必需模型是否成功，而不是仅有日志。
6. 效果对象是否赋给正确属性且 `enable` 状态正确。

### 模型初始化失败

- 记录 NVE model type 和非敏感文件名。
- 检查是否使用了旧文档文件名、错误 bundle、错误版本或目录而非文件。
- 检查 `faceCommon` 是否误用 `face` 类型。
- 不用一个“相近模型”替代另一个类型。
- 可选模型失败时禁用对应道具能力；基础模型失败时停止人脸效果链。

### 滤镜/美妆第一次有效，第二次失效

- 检查是否把 `AlreadyInstalled` 当失败。
- 检查重复安装时 package ID 是否为空且未回查。
- 检查单选逻辑是否误删整个 container。
- 检查是否每次创建新 effect object，但 UI 修改的是旧对象。

### 组合妆只有滤镜/美颜，口红眼影等彩妆缺失

先检查组合妆赋值后的最终状态，不要先修改资源 JSON 或整体强度：

1. 确认 `kit.composeMakeup = compose` 成功，且目录中的 makeup 项、package 和证书完整。
2. 检查同一次状态提交后是否又执行了 `makeup.enable = false`，或把 enable 只绑定到 `hasSingleMakeup` 等“是否存在单项美妆”的状态。
3. 组合妆激活时保持 `NveMakeup` 启用；若必须统一计算，使用“存在单项美妆或组合妆激活”的条件。移除组合妆后再按产品快照恢复单妆状态。
4. 用一套同时包含口红/眼影和滤镜/美颜的妆容验证。只剩滤镜或美颜通常说明组合妆已部分加载，但 `NveMakeup` 域随后被覆盖关闭。
5. 状态正确后仍有轻微颜色或位置差异，再核对输入 pixel format、`imageOrientation`、`mirror` 和 `isFromFrontCamera`；不要用方向或色彩调整掩盖 enable 顺序错误。

若组合妆上的单妆覆盖清除后没有恢复原妆容部位，检查产品是否声明了“恢复组合妆”语义。清空覆盖 package ID 只会移除当前分类，不保证 SDK 自动找回此前被覆盖的组合项；按声明状态重放当前组合妆，再按顺序重放其余单妆覆盖。若 A→B 后旧单妆覆盖丢失或错误保留，同样检查状态是否分层保存了组合妆基底和单妆覆盖，而不是从当前 `NveMakeup` 对象反推选择。

manifest 加载异常时记录经过脱敏的条目标识和失败类型，依次检查 JSON、资源根目录内的标准化路径、package 目录/文件和证书。绝对路径或 `..` 越界必须拒绝；失败时保留旧效果，不要用空对象、空 package ID 或默认选中态覆盖当前状态。

### 动态滤镜清除后仍残留或切换滞后

先区分“SDK 仍在渲染旧效果”和“显示层仍在展示旧帧”，不要把两者都归因于 `remove:`：

1. 在同一状态事件中记录 owner 对象移除结果、container 快照、首个新代际渲染帧和首个新代际显示帧。
2. 若新渲染帧仍包含旧效果，检查是否移除了同一 owner 对象、是否存在其他 owner 的同 `effectId`，以及状态变更是否与 render 串行；不要直接改用 `removeAll`。
3. 若新渲染帧正确但屏幕仍残留，检查 latest-frame mailbox 是否带 generation/epoch、旧 pending 帧是否失效，以及主线程已排队 block 是否会回灌。
4. `AVSampleBufferDisplayLayer.flush()` 不移除当前图像。需要清除旧效果画面时使用 `flushAndRemoveImage()`，或在首个新代际帧到达时原子替换。
5. 若首次选择或切换大素材时画面长时间停留，检查 `installAssetPackage` 是否运行在 capture/render 队列。小且已知的素材集可在帧流前预安装；大目录使用独立准备队列按需预热。

已缓存的“动态滤镜→无”和“动态滤镜→其他滤镜”仍出现秒级旧画面或回跳属于失败。单独验证摄像头画面是否仍在运动，避免把冻结的最后一帧误判成 SDK 持续渲染。

### 单妆或组合妆每次切换都延迟 2–5 秒

先用同一个切换事件 ID 分段记录：素材缓存命中/安装结束、状态提交、首个新状态渲染帧、首个新状态显示帧。不要用总耗时猜原因，也不要在生产环境逐帧打印。

- 若缓存阶段慢：确认素材以稳定 key 缓存真实 package ID，A/B 来回切换不再调用安装；`AlreadyInstalled` 不是每次重走安装流程的理由。
- 若状态提交慢：确认会话只创建并绑定一次 `NveMakeup`。切换只改现有对象对应分类的 package ID/强度；重复 `kit.makeup = sameObject` 在部分版本会重建内部效果链。
- 若组合妆 A→B 状态提交慢：确认 A/B 已在帧流前解析并缓存，直接执行 `kit.composeMakeup = B`，不得先设 `nil`，也不得先全量清空九类单妆；赋值后只按稳定顺序重放仍存在的单妆覆盖。
- `composeMakeup = nil` 只用于用户明确选择“妆容-无”或“清除全部”。把它作为普通替换前的清理步骤会先拆除再重建效果链，是 2–5 秒空档的高风险根因。
- 若 Main Thread Checker 指向 `NveMakeup` 属性：用 mutation gate 暂停新帧，`main.async` 完成短属性变更，再 `renderQueue.async` 提交状态并解除 gate。禁止 `renderQueue → main.sync`，也禁止主线程同步等待 render queue。
- 若新状态很快完成 render、但数秒后才显示：检查 `main.async` 帧堆积、`AVSampleBufferDisplayLayer` 背压和旧 sample buffer 队列。使用容量 1 的 latest-frame mailbox，并在状态断点清掉已排队旧帧。
- 若日志持续读取 `advancedbeauty/mask0.png`：检查是否照搬 demo 的非零高级美颜默认值（如去黑眼圈、亮眼），却没有配置对应模型/资源。验证入口默认保持这些参数为 `0`；只有产品明确启用且模型/资源完整时再打开。不要通过加载无关模型来掩盖配置错误。

预热后的 A→B→A→B 仍稳定出现秒级间隔属于失败。验收需同时证明没有重复安装、没有重复绑定、组合妆替换前没有赋 `nil` 或全量 reset 单妆、没有 Main Thread Checker 告警、没有持续资源读取错误，并区分“首帧已渲染”和“首帧已显示”。

### 美颜 slider 拖动闪黑或效果滞后

- 检查 slider setter 是否每次都 `renderQueue.async`。连续事件会排在 capture frame 前面，导致效果落后；改为只覆盖一个 pending latest state，并在下一帧 render 前消费一次。
- 检查 slider/value change 是否递增 generation 后调用 `flush` 或 `flushAndRemoveImage`。强度变化不应刷新显示层；容量为 1 的帧 mailbox 会淘汰旧帧。
- 检查每次更新是否重新写入全部美颜/美型/微整形参数。保留 applied typed state，只差量更新变化属性。
- 若状态已在下一帧 render 前提交但显示仍慢，再检查主线程帧任务、`isReadyForMoreMediaData` 和 display layer 背压。

### 切换摄像头时短暂左右颠倒

- 检查全局 camera position 是否在旧 sample buffer 排空前提前改变；在途旧帧会因此使用新镜像方向。
- 重配期间设置 transition gate 并丢弃帧，完成配置后在串行 render 队列排到旧帧之后再提交新 position。
- 切换 input 后重新应用 video connection 的方向/rotation angle 和 capture mirroring 策略；不能假设旧 connection 配置自动保留。
- 默认链让 `image.mirror` 使用本帧 front-camera 快照；只有完成全零输出 A/B 取证的兼容链，才在 connection 重配时设置 capture 镜像并令 `image.mirror = false`。两条链的 preview 都不再镜像，owned preview frame 只需 generation。
- 只有产品明确采用 preview-consumer 镜像时，每帧才携带 mirror 快照，并在首个新代际帧显示时原子更新 transform 与 enqueue。不得把同一快照同时用于 `image.mirror` 和 preview `scaleX = -1`。

### 画面黑屏、绿屏或花屏

- 核对 render mode 与必填输入。
- 输出 buffer 模式检查 OSType；texture 模式检查当前 EAGLContext、texture ID、尺寸和 layout。
- 确认没有把 `MTLTexture` 当 OpenGL texture。
- 检查输出是否在异步消费者完成前被回收。
- 检查 `overlayInputBuffer` 是否对只读/共享输入做原地写入。
- 在 output 回收前比较源与 SDK 输出的尺寸、OSType、plane 数，并在诊断构建对 Y/UV 做固定网格稀疏采样；不要只看 `errorCode` 和非空指针。
- 若源 NV12 有效而 SDK 输出 Y/UV 全零，等待 GPU 完成后仍不恢复，按本帧记录 `image.mirror` 与 `isFromFrontCamera`。只在前摄 SDK mirror 开启时发生时，用下一有效帧关闭 `image.mirror` 做一次 A/B 隔离。
- A/B 证明 SDK mirror 是唯一触发条件后，按 [帧方向与镜像契约](frame-geometry-contract.md) 启用 `captureMirrored`：capture 成为唯一 mirror owner，NVE mirror 固定关闭，front-camera 来源标记保留。
- 不在生产帧循环中检测全零后自动切策略；策略切换会改变检测、预览和录制的几何语义。未完成真机 A/B 时保持默认策略并报告阻塞。

### 人脸效果方向错误或道具漂移

- 先执行 [帧方向与镜像契约](frame-geometry-contract.md) 的方向账本和六步取证，未取证前不改角度。
- 默认 `AVCaptureVideoDataOutput → buffer-buffer` 链由 connection 负责旋转、NVE 负责 mirror；已取证 `captureMirrored` 链由 connection 同时负责旋转和 mirror。两者的 preview 都无 transform。
- 出现 `connection.videoOrientation`、`image.displayRotation`、preview rotation 中两个以上 owner 时先删除重复 owner；不得用另一层反向旋转抵消。
- 出现 `image.mirror = isFrontCamera` 和 preview `scaleX = -1` 时属于双重镜像。
- texture 模式若提供检测 buffer，确认它和 texture 是同一帧、同一方向；texture layout 不替代 rotation。
- 用前后摄像头和带文字/非对称素材验证；无真机时只能报告静态重复项已清理，方向仍未验收。

### 崩溃或偶现错误

- 检查 render 是否并发调用。
- 检查销毁时是否仍有帧进入。
- 检查 output 是否重复回收、漏回收或异步 use-after-recycle。
- 检查 GL context 是否跨线程错误使用。
- 检查 UI 是否在另一个线程替换效果对象的同时 render；必要时通过客户媒体队列串行提交状态变更。

### 模拟器无法链接

- 检查客户 framework/XCFramework 是否包含模拟器 slice。当前基线 NveEffectKit 仅声明 iPhoneOS。
- 不通过排除 arm64 等全局配置破坏真机架构；要求供应方提供正确 simulator/XCFramework 交付，或只做真机验证。

## 性能策略

初始化：

- 只加载请求功能必需模型。滤镜无需默认加载人脸模型。
- 完整美肤和完整美颜默认包含高级美肤，需加载 `advancedBeauty`；自定义具体控件按基线最小加载。
- 素材能力未知时先索取能力清单；明确 `none` 后才能证明无需附加检测模型。
- 高/低规格分割模型通过可配置能力策略选择，并记录设备和模型。
- 授权、模型初始化和素材安装在帧流开始前完成或由独立准备队列受控异步完成；不要让安装任务排在 capture/render 串行队列中阻塞后续帧。

逐帧热路径：

- 禁止文件 I/O、JSON 解析、图片解码、素材安装和 bundle 全目录扫描。
- 复用效果对象、renderer owner、EAGLContext 和输出消费链。
- 根据上下游选择模式，避免 buffer↔texture 往返。
- 只在格式确实不支持时转换 pixel buffer。
- 在串行队列上测量 NVE `renderTime`、总帧耗时和丢帧，不在生产日志逐帧打印。
- 异步预览采用有界队列或容量 1 的 latest-frame mailbox；禁止每帧无界追加主线程任务。

验证指标：

- 记录设备、系统、SDK、分辨率、帧率、输入格式、render mode 和启用功能。
- 比较无效果、单效果、组合效果的 p50/p95 帧耗时。
- 连续运行并反复切换效果，观察常驻内存、纹理/buffer 数和温升趋势。
- 对效果切换分别测量状态提交、首个新状态渲染帧和首个新状态显示帧；渲染耗时正常但显示延迟大时优先排查下游积压。
- 验收重点是无持续的资源泄漏和无异常帧积压；固定毫秒阈值由产品目标和目标设备决定，skill 不擅自定义。

## 安全与日志

- 永不读取、打印、提交或嵌入 SDK/素材 `.lic` 内容。
- 日志只记录是否存在、脱敏文件名、错误枚举、SDK 版本、格式和尺寸。
- 不上传客户帧、模型、素材或工程配置到外部服务。
- 不从网络自动下载商业 SDK/素材；缺失时要求客户从正式商务/技术支持渠道获取。
- 路径参数使用解析后的本地路径并检查位于客户明确提供的根目录内；不要通过素材文件名拼接任意父目录。

## 资料中的已知偏差

- 接入文档/官网示例仍使用旧模型文件名，与 3.16.1 实际资源不一致。
- 文档把 `facecommon` 以 `face` 类型初始化一次，又以 `faceCommon` 初始化一次；只保留后者映射。
- 文档的 shape 示例误赋 `beauty`。
- demo 工程 deployment target 与 framework MinimumOSVersion 不一致。
- `beautyEffect.json` 与 `beautyEffect_gan.json` 不是严格合法 JSON。
- demo 部分安装逻辑只接受 `NoError`，遗漏 `AlreadyInstalled`。
- demo 微整形恢复/开关引用错误对象。
- demo 录制时间换算依赖其内部 writer，不能推导 `renderTimestamp` 单位。
- demo 只完整演示 buffer 输入；texture 模式必须在客户 Mac/真机环境单独验证。

## 升级审计

收到新版本资料时：

1. 运行 `audit_vendor_drop.py`。
2. 审阅版本、MinimumOSVersion、SupportedPlatforms、公共头文件 API、模型文件名和素材扩展名差异。
3. 检查 NveEffectKit 与 core SDK 变体是否变化。
4. 在临时副本上更新机器基线，禁止自动覆盖现有 skill。
5. 更新受影响的引用和 Objective-C/Swift 模板。
6. 重跑静态测试、Mac 编译、真机效果和隔离前向测试。
