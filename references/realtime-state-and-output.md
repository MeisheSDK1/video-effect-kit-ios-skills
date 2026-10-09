# 实时效果状态与输出消费规范

## 目录

- [适用范围](#适用范围)
- [事实来源与语言选择](#事实来源与语言选择)
- [唯一状态模型](#唯一状态模型)
- [逐帧提交顺序](#逐帧提交顺序)
- [输出所有权与消费者策略](#输出所有权与消费者策略)
- [录制边界](#录制边界)
- [摄像头切换](#摄像头切换)
- [功能模块适配契约](#功能模块适配契约)
- [默认 UI 边界](#默认-ui-边界)
- [模板使用与扩展规则](#模板使用与扩展规则)

## 适用范围

修改实时相机/直播链中的美颜、美型、微整形、美妆、组合妆容、滤镜、道具、分割或自定义效果状态，或者把渲染结果交给预览、录制、RTC/直播或其他异步消费者时，统一遵守本规范。它描述与 Swift、Objective-C 无关的 owner、状态、线程、输出分流和资源生命周期；模块属性和素材映射仍从 `baseline-3.16.1.json` 及对应功能参考读取。

同步消费且没有 UI 高频状态、异步输出或摄像头切换时，只使用通用 render/recycle 规则，不强行引入 mailbox 或额外 coordinator。效果模块和输出消费者是两层：前者修改本帧效果，后者决定渲染结果如何预览、录制或发送；录制不是效果模块。

## 事实来源与语言选择

按职责选择事实来源，不能用一种来源覆盖所有问题：

1. SDK 符号、枚举、空值、范围和所有权：以客户实际二进制公共头文件为准。
2. NVE 对象创建、赋值和素材应用语义：以客户实际公共头文件、同版本基线和编译结果为准。
3. 相机、帧队列、预览、录制和 UI 架构：以客户现有工程为准，不引入第二套页面或媒体架构。
4. Swift 导入名称和 Optional/closure 形式：以客户 framework 在 Xcode 中的实际编译结果为准。

实现语言跟随被修改的现有 owner：

- Swift owner 用 Swift；Objective-C owner 用 Objective-C。
- 混编工程不为了接入效果新增跨语言逐帧调用边界。
- 允许依据下述伪代码转换语言，但必须编译验证实际 SDK 符号。
- 不因为 Swift 更常用于新项目，就把 Objective-C 客户工程迁移到 Swift。

## 唯一状态模型

每个媒体会话维护以下角色，名称可跟随客户工程：

| 角色 | 责任 |
| --- | --- |
| desired state | UI/业务已经确认的完整 typed state |
| pending latest state | 容量为 1；等待下一帧提交的最新快照 |
| applied state | 已成功提交给 SDK 的快照，用于计算差量 |
| module adapter | 持有长生命周期 SDK 对象，把 state delta 映射到 SDK |
| frame state | 本帧的 camera position、mirror、orientation、generation |
| output router | 在回收前为每个异步消费者建立独立所有权 |
| preview mailbox | 容量为 1；只保存调用方拥有的最新预览帧 |
| ordered output consumer | 按时间线消费录制/编码/RTC 帧，并执行其自身背压策略 |

UI/业务事件只做归约和覆盖，不向 render queue 逐事件追加任务：

```text
onEffectEvent(event):
    next = reduce(desiredState, event)
    desiredState = next
    pendingLatestState = next       // overwrite, never append
    publishObservableState(next)
```

创建状态盒时必须同时令 `desiredState = initialState`、`pendingLatestState = initialState`，使非零产品默认值在第一帧 render 前应用。只初始化 desired 而把 pending 留空会造成 UI 已显示默认值、SDK 仍保持零值，直到首次交互才生效。

typed state 保存产品语义，不直接暴露 `NveBeauty`、`NveMakeup`、`NveFilter` 等 SDK 对象。状态至少能表达：

- 模块启用状态；
- 当前参数、强度、选中素材和真实 package ID；
- 重置/移除所需的 owner 标识；
- 组合妆容等跨模块操作应用前的恢复快照。

## 逐帧提交顺序

所有 SDK effect mutation 和 `renderEffect` 在同一稳定串行 frame queue 执行：

```text
onInputFrame(sourceFrame):
    frameState = cameraTransition.snapshot()
    if frameState is unavailable:
        drop sourceFrame
        return

    latest = takeAndClear(pendingLatestState)
    if latest exists:
        delta = diff(appliedState, latest)
        moduleAdapters.apply(delta)
        appliedState = latest

    output = renderEffect(sourceFrame, frameState)
    if output is null:
        report error
        return

    try:
        validate output
        establish ownership for every asynchronous consumer
    finally:
        recycle output exactly once

    previewConsumer.publishLatest(ownedPreviewFrame)
    recordingConsumer.submitOrdered(ownedRecordingFrame, sourcePTS)
```

约束：

- 一帧最多消费一次 pending state；连续 slider 事件只保留最终值。
- `apply(delta)` 只修改变化属性，不重建未变化对象，不重复安装素材。
- 普通强度、enable、reset 不递增预览 generation，也不刷新显示层。
- 素材准备失败时保留 applied state 和当前画面，不发布“已切换”状态。
- 若 SDK 某属性经实际 Main Thread Checker 证明必须在主线程访问，先暂停新 frame mutation，再执行短主线程变更；禁止主线程反向同步等待 frame queue。

## 输出所有权与消费者策略

`NveRenderOutput` 及其 payload 默认由 NVE 管理。异步消费者必须在回收前选择且实现一种策略：

1. 下游 API 明确保证同步复制/retain；
2. 在 output 消费作用域内复制到调用方自有 buffer/texture；
3. 用唯一 lease owner 延迟回收，直到 completion。

没有明确契约时使用策略 2。不能把即将回收的 `output.pixelBuffer` 直接排到主线程、录制队列或编码队列。一个 render output 可以分流给多个消费者，但每个消费者都必须在 `recycleOutput` 前获得自己的 copy、retain 或 lease；不能假设预览持有就等于录制也安全。

各消费者的背压策略不能混用：

| 消费者 | 顺序与丢帧策略 | 典型实现 |
| --- | --- | --- |
| 预览 | 容量为 1，latest wins；显示层不就绪时可丢旧帧 | capacity-one mailbox |
| 录制/文件编码 | 保持 PTS 单调和既定时间线；只按客户录制器的明确策略丢帧 | existing recorder/encoder queue |
| RTC/直播 | 遵守现有发送器的拥塞、关键帧和时间戳契约 | existing transport/encoder |

异步 preview mailbox 只用于预览，并且只接收已经完成最终 rotation/mirror 的 presentation-ready owned frame：

```text
publish(ownedFrame):
    ownedFrame.generation = currentGeneration
    pendingPreviewFrame = ownedFrame    // replace old pending frame
    schedule at most one main-thread drain

drain():
    frame = takeAndClear(pendingPreviewFrame)
    if frame.generation == currentGeneration
       and display is ready:
        enqueue(frame)
    if another frame arrived:
        schedule one more drain
```

默认 NVE-owned 与已取证 capture-owned 相机链的 preview view 都不执行 rotation、bounds 交换或 mirror transform；几何规则见 [帧方向与镜像契约](frame-geometry-contract.md)。客户已有且已验证 preview-only mirror 时保留独立 preview consumer copy 和显式产品契约，不能把 view transform 叠加到已经镜像的像素。

同时设置 `AVCaptureVideoDataOutput.alwaysDiscardsLateVideoFrames = YES/true`。显示层不就绪时丢帧，不能建立无界 `main.async` 队列。

## 录制边界

具体的 writer 顺序、镜像、输出所有权和已验证 UI 见 [录制输出接入规范](recording-output.md)。

优先复用客户工程现有录制器、编码器、音频链和会话 owner；不能因为接入 NVE 就新建第二套 `AVAssetWriter` 或改变产品既有丢帧策略。录制接入至少满足：

1. NVE 授权、模型、实例和效果状态 ready 后再允许开始录制。
2. 使用源帧/客户录制器的 PTS，保持单调时间线；音频存在时继续遵守原有 A/V 同步契约。`renderTimestamp` 未知时基时保持 SDK 默认，它不能替代录制 PTS。
3. 明确成片镜像产品契约。成片可以与前置镜像预览一致，也可以保持真实非镜像；若两者不同，必须在消费者边界分别处理，不能让同一原地覆盖 buffer 同时满足两种方向。
4. preview generation、`flushAndRemoveImage` 和预览丢帧只影响预览，不能清空录制队列或改变录制时间线。
5. 切换摄像头、分辨率、像素格式或 capture session 时，按客户产品已有规则决定连续录制、分段或禁止切换，并在旧帧排空后提交新格式；不能把新 camera/mirror 状态套到在途旧帧。
6. 停止时先停止并断开新输入，再 finish/drain 录制器或编码器、排空 render queue，最后释放效果对象并由唯一 owner `destroyInstance`。
7. 录制开始/暂停/停止状态与美颜、美妆、滤镜、道具等效果 enable/reset 状态分离；切换效果面板不能隐式改变录制状态。
8. 停止 writer 时先 `markAsFinished` 再 `finishWriting`；完成后验证文件可读且非空，相册保存失败时按产品规则保留本地文件。

录制不能复用 preview 的 capacity-one mailbox。若客户录制器背压时允许丢视频帧，丢帧位置、PTS 处理和音频同步必须沿用其显式策略并完成真机验收，不能由通用效果模板猜测。

## 摄像头切换

按以下顺序隔离在途旧帧：

```text
before capture reconfiguration:
    cameraTransition.active = true

replace camera input
reapply video connection orientation/mirroring policy
commit capture configuration
previewGeneration += 1
pendingPreviewFrame = nil
remove old displayed image when product requires it

renderQueue.async barrier:
    cameraPosition = committedPosition
    cameraTransition.active = false
```

- transition active 时 frame callback 丢帧。
- 每个 frame 保存自己的 `isFrontCamera` 快照，不能在 render 或异步消费时重新读取全局 camera position。
- 默认链在 NVE 输入中按快照完成 mirror；已取证兼容链在 capture connection 中完成 mirror。两者的 owned preview frame 都只携带 generation，首个新摄像头帧直接 enqueue，不改变 view transform。
- 只有产品明确采用 preview-consumer 镜像时，frame 才额外携带自己的 `isMirrored`，并在首个新代际帧到达时把移除旧图、更新 transform 和 enqueue 作为一个主线程顺序动作。
- 不用双重 mirror 或逐帧策略切换掩盖竞态；完整互斥与 SDK 全零兼容规则见 [帧方向与镜像契约](frame-geometry-contract.md)。

## 功能模块适配契约

每个效果模块只实现自己的 adapter，不复制 capture、render 或 output coordinator：

```text
module.prepare(resources)       // frame queue 外安装/解析/预热
module.createLongLivedObjects()
module.reduce(state, event)
module.diff(applied, desired)
module.apply(delta)             // 与 render 串行
module.reset(scope)
module.removeOwnedObjects()
```

新增美妆、滤镜、道具、分割或自定义效果模块时优先更新：

1. `baseline-3.16.1.json` 中属性、范围、模型、素材类型和 container 映射；
2. 对应功能 reference 中的对象复用、切换、重置和验收规则；
3. `validate_integration.py` 中可静态证明的高风险约束；
4. 只有存在语言专属且反复出错的编译/所有权骨架时才增加模板。

模块切换是否形成 preview generation 断点由预览语义决定。普通参数变化不是断点；会导致旧内容不可继续显示的效果图重建、camera/session/output 格式变化才是断点。该断点不自动传播给录制/RTC 消费者，它们按自己的 session 与时间线契约处理。

## 默认 UI 边界

UI 的视觉和布局不是 SDK 模板：

1. 用户有明确设计时遵循用户设计。
2. 项目有设计系统或可复用效果面板时复用现有体系。
3. 两者都没有时按对应功能 reference 的默认交互契约实现。

不要把 SwiftUI/UIKit 页面作为通用 SDK 模板。只有同一 UI 技术栈在多个真实客户项目中稳定复用并完成可访问性、布局和交互验证后，才考虑增加可选 UI asset。

## 模板使用与扩展规则

当前模板分工：

- `assets/templates/objective-c/NVEEffectSession.h/.m`：供应方 Objective-C API 的通用生命周期、render 和 recycle 基准。
- `assets/templates/swift/NVESwiftSDKInterop.swift`：只保留模型初始化、`renderEffect`/`recycle(_:)` 等易错 Swift 导入写法，不复制 session。
- `assets/templates/swift/NVEFrameGeometry.swift`：强制选择默认 upstream-oriented、已取证 capture-mirrored 或有证据的显式 SDK 方向元数据，避免同帧存在多个 owner。
- `assets/templates/swift/NVERealtimeStateCoordinator.swift`：latest-state 和 camera transition 的编译验证过的 Swift 写法。
- `assets/templates/swift/NVEOutputOwnership.swift`：异步消费者在回收前复制 pixel buffer 的编译验证过的 Swift 写法。
- `assets/templates/swift/NVEAsyncPreviewBridge.swift`：capacity-one preview mailbox 和无 transform 显示层的编译验证过的 Swift 写法，仅用于 presentation-ready 预览。

裁剪与客户 owner 匹配的部分，不整包复制。

录制、RTC/直播等消费者优先接入客户现有实现并执行本规范，不提供通用 writer/transport 模板。只有从至少两个真实接入证明存在稳定、跨项目且无法由规范表达的共同骨架后，才评估增加薄模板。

增加新模板必须同时满足：

- 解决已复现的高频或高风险问题，而不是预想需求；
- 代码结构跨两个以上效果模块或输出消费者的真实接入可复用，或者存在无法仅靠规范消除的语言/API 导入陷阱；
- 已使用客户实际 SDK 头文件/二进制完成编译验证；
- 有自测约束关键所有权、线程或顺序不变量。

模块属性清单、素材 UUID、证书名、产品默认值和 UI 视觉不要硬编码进语言模板。
