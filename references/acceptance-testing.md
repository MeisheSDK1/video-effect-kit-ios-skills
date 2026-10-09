# 接入后自动验收

## 目录

- [适用范围](#适用范围)
- [分层流水线](#分层流水线)
- [最小 UI 自动化契约](#最小-ui-自动化契约)
- [功能验收矩阵](#功能验收矩阵)
- [运行环境阻塞](#运行环境阻塞)
- [结果报告](#结果报告)

## 适用范围

`first-integration` 和 `add-feature` 完成后必须自动执行能在客户环境运行的全部层级。`repair` 执行针对复现路径的回归测试；`optimize` 执行原有功能 smoke + 性能对比；纯 `audit` 不修改也不强制运行。

自动化结论必须区分 `通过`、`失败`、`未执行（有明确阻塞）`。构建成功不能写成“功能验证通过”。

## 分层流水线

### A. 静态集成验证（必跑）

```text
python3 -B <skill>/scripts/validate_integration.py \
  --project-root <项目根目录> \
  [--sdk-root <用户授权的SDK搜索根目录>] \
  [--resource-root <用户授权的模型/素材搜索根目录>] \
  [--sdk-license <明确SDK授权路径>] [--model <明确模型路径>] \
  [--asset <明确素材路径> --asset-license <明确素材证书路径>] \
  --features <实际接入的稳定功能ID> \
  [--beauty-control <自定义控件ID>] \
  [--asset-capability <素材能力或none>] \
  [--compose-root <已解压妆容目录>] \
  [采用无设计默认 UI 时 --default-ui] \
  [请求默认录制 UI 时 --recording-ui]
```

检查授权顺序、core 变体、最低系统、模型、渲染/回收、素材安装和 container。采用 skill 默认 UI 时必须显式传 `--default-ui`；请求默认录制 UI 时再传 `--recording-ui`，验证器据此检查固定 accessibility 标识、`NVEEffectTheme`/`nve.default-theme.v1` 主题契约、各默认 UI 源文件对共享主题的引用，以及“录制不得新增独立 panel”等可静态证明的结构约束；控件层级、条件式显隐和解析后的实际颜色仍由 UI 测试负责。`--project-root` 只扫描生产源码和工程配置；商业文件只从另外显式提供的精确路径、`--sdk-root` 或可重复的 `--resource-root` 验证。每个必需模型必须同时确认文件存在、对应 `NveDetectionModelType_*` 与正确文件路径绑定后传给 `initHumanDetection`，且初始化发生在 `shareInstance` 前；交换模型路径、只出现枚举或执行一次任意模型初始化都不能代替完整映射。静态扫描不能证明运行时效果，但可以阻止明显接入错误。

### B. 编译验证（Mac/Xcode 必跑）

```text
bash <skill>/scripts/macos_smoke_test.sh \
  --workspace <workspace> --scheme <scheme> \
  --destination 'generic/platform=iOS'
```

对只有 device slice 的交付使用 generic iOS build。若 SDK 支持模拟器，可改用具体 simulator destination。

本地随包素材必须另外验证进入构建产物；使用隔离 DerivedData，并为实际运行时相对路径重复传入 `--require-resource`：

```text
bash <skill>/scripts/macos_smoke_test.sh \
  --workspace <workspace> --scheme <scheme> \
  --destination 'generic/platform=iOS' \
  --derived-data <临时目录>/DerivedData \
  --require-resource filter.bundle/filter.json \
  --require-resource filter.bundle/<所选素材>.videofx \
  --require-resource filter.bundle/<配套证书>.lic
```

脚本只验证指定路径存在于本次构建产生的某个 `.app`；远程下载素材改由启动 smoke 验证客户资源管理器返回的可读缓存 URL。

### C. 启动与交互 smoke（环境支持时必跑）

优先复用客户已有 UI test target。若 `first-integration`/`add-feature` 改动了用户可点击入口且存在可运行的 simulator/真机 destination，必须保证至少有一个最小 `NVEFeatureSmokeTests`：已有 target 就复用；没有 target 时，在不破坏客户测试架构的前提下新增最小 UI test target。然后运行：

```text
bash <skill>/scripts/macos_smoke_test.sh \
  --workspace <workspace> --scheme <可测试scheme> \
  --destination 'platform=iOS Simulator,name=<可用设备>' \
  --test --only-testing '<UITestTarget>/NVEFeatureSmokeTests' \
  --result-bundle <临时目录>/NVEFeatureSmoke.xcresult
```

测试动作应在 60 秒内完成单个用例，脚本默认开启 XCTest 超时。只有 framework 支持目标运行平台时才运行；不能通过排除架构伪造模拟器支持。

### D. 真机效果与性能（人脸/相机/仅 device SDK）

需要签名真机、有效 Bundle-ID 授权、相机输入及目标素材。自动化至少运行已有 device UI/unit tests；视觉效果、前后摄方向、遮挡和帧耗时用项目已有截图/指标钩子断言。没有可控真机时，把这一层标为阻塞并给出所需设备、签名、授权和素材，不得声称通过。

实时相机首次接入或方向修复时，方向/镜像是发布阻塞验收，不是普通剩余风险。必须执行 [帧方向与镜像契约](frame-geometry-contract.md)：后摄竖屏、前摄竖屏、前→后→前、后→前输出 plane 有效性和非对称/带文字画面。没有可靠相机输入时允许交付已编译代码，但总状态只能写“代码接入，方向/镜像未验收”，不得写“完整接入完成”或“方向已修复”。

默认使用 NVE-owned mirror。只有诊断构建记录“源 Y/UV 非零、NVE mirror 输出全零、关闭 NVE mirror 后恢复”的 A/B 摘要，才接受 capture-owned mirror；验收报告必须写明 owner、设备、SDK/core 版本和录制镜像影响。不能用一次视觉正常或编译通过代替该证据，也不能在生产帧循环中自动切换 owner。

## 最小 UI 自动化契约

顶层功能模块采用独立面板契约：美颜、美妆、滤镜、道具、分割等各自拥有独立入口和独立 panel，不把后接入的模块作为其他模块内部 tab。为保持预览可见，产品可以一次只展开一个 panel；打开另一个模块时应收起当前 panel，但不能清除任一模块已应用的效果或选择状态。模块内部的分类、参数和可选 tab 不受此约束。

不要依赖坐标点击。给新入口和关键状态添加稳定的 accessibility identifier，并尽量复用客户命名规范：

```text
nve.<feature>.entry
nve.<feature>.panel
nve.<feature>.panel.show
nve.<feature>.panel.hide
nve.<feature>.enable
nve.<feature>.parameter.select
nve.<feature>.intensity
nve.<feature>.clear
nve.<feature>.loading
nve.<feature>.error
nve.<feature>.prompt
nve.preview
```

每个新增可点击功能至少覆盖：

1. App/目标页面在超时内启动，未崩溃、未卡死。
2. 功能入口存在且 `isHittable`，点击后本模块 panel、selected 状态或可观测 state 改变；客户已有 UI 使用其产品约定的收起动作，skill 默认 UI 只使用面板外空白点击关闭；再次打开时状态保留。
3. 启用一个效果、修改一次强度或选项、再清除；每次都断言状态变化，不能只执行 tap。
4. 对素材选择执行 A→B→A→B，覆盖已安装缓存、对象复用和显示链清旧帧路径；已缓存素材的切换不得出现秒级空档。
5. 返回/重新进入页面后仍能点击；销毁重建路径不崩溃。
6. 验证面板存在收起与恢复路径；默认 UI 中底部入口与面板必须互斥，只能点击面板外空白区域收起，面板内不存在专用收起或关闭按钮。恢复后参数值与启用状态不丢失。
7. 相机或单图验证页在面板展开、收起前后都保留可观察的 preview；不要用全屏 modal 或纵向全参数列表长期覆盖效果区域。
8. 工程有两个以上效果模块时，分别验证每个 `nve.<feature>.entry` 只控制自己的 panel；从一个模块切到另一个模块后，前一模块效果状态仍保留，且不是通过共享 tab 冒充独立入口。
9. 滤镜的“无”是独立选择状态：选中后目标滤镜已移除、强度控件不存在，而不是仍显示一个禁用 slider；panel 标题区不使用“无滤镜”等静态文案冒充选择状态。
10. 默认道具 UI 中“无”固定在第一项且不显示强度控件；素材准备或 prop 创建失败时保留原选中态和原提示，只有应用成功后才发布新选中态。
11. 采用默认底部操作栏时，在最小支持设备宽度验证入口等宽、标题单行、无裁切/重叠且触控高度至少 `44 pt`；展开每个效果面板，验证入口栏和所有面板在同一底部容器中互斥切换、复用同一底部间距来源且没有忽略底部安全区。客户工程没有 spacing token 时，静态或布局断言确认共享默认基线为 `10 pt`。用户已声明近期增加第 5 个入口时，用 Preview、测试 fixture 或临时调试数据验证五项容量，完成后移除无功能占位数据。
12. 请求采用默认录制 UI 时，按 [默认效果 UI](default-ui.md) 验证共享底栏、录制入口、摄像头切换和完成提示，并按 [录制输出接入规范](recording-output.md) 验证状态机。
13. 采用 skill 默认 UI 时，按 `default-ui.md` 的“固定控件与层级”检查可访问性树：美颜必须存在功能域、参数列表、数值、slider、重置和开关；完整美妆必须存在分类、分隔和“无”开头的素材列表且不存在默认 slider；滤镜必须存在操作说明和“无”开头的素材列表，选中具体滤镜后才出现数值与 slider；道具必须存在操作说明和“无”开头的素材列表，只有非空提示时才出现提示行且始终不存在 slider；录制只有共享底栏按钮，不存在独立录制 panel。
14. 默认 UI 的结构断言检查控件种类、父子层级、条件式显隐和禁止项，不断言图标、字体、圆角、精确尺寸或任何底栏入口的先后顺序。入口等宽、标题单行、触控高度和安全区继续由布局断言覆盖，不使用全屏像素完全相等作为唯一证据。
15. 默认 UI 的主题断言必须证明共享底栏和全部面板读取同一个 `NVEEffectTheme` 实例或同一客户主题映射，并比较解析后的背景、边框、分隔线、主/次文字、选中/未选中卡片、slider、Toggle、禁用态和状态色。使用 `nve.default-theme.v1` 时按默认 token 值断言；使用客户主题映射时按映射值断言。任一面板出现独立强调色、独立背景/边框或组件内硬编码主题颜色均判为失败。

轻量 XCTest UI 骨架（按客户导航替换，不照抄标识之外的页面结构）：

```swift
func testNVEFeatureSmoke() {
    let app = XCUIApplication()
    app.launchArguments += ["-NVEUITest", "1"]
    app.launch()

    let entry = app.buttons["nve.<feature>.entry"]
    XCTAssertTrue(entry.waitForExistence(timeout: 10))
    XCTAssertTrue(entry.isHittable)
    entry.tap()

    let panel = app.otherElements["nve.<feature>.panel"]
    XCTAssertTrue(panel.waitForExistence(timeout: 3))
    let clear = app.buttons["nve.<feature>.clear"]
    XCTAssertTrue(clear.isHittable)
    clear.tap()
}
```

不要为了 smoke 引入第三方测试框架或整套页面对象架构。若项目限制禁止新增 target、scheme 不可测试、SDK 没有可运行 slice 或缺少签名设备，则执行 A+B，把 C 标为“未执行”，准确列出恢复条件并提供最短人工 smoke 清单；不能把人工清单写成自动化通过。

## 功能验收矩阵

| 功能 | 自动化必须断言 | 运行时补充 |
| --- | --- | --- |
| beauty | 美肤 panel 可开、enable/强度状态变化、clear 恢复 | 真机有人脸时确认磨皮/美白/红润生效 |
| shape/micro-shape | 对应 panel 可开、enable/强度状态变化、clear 恢复 | 真机有人脸时确认效果不漂移 |
| beauty-suite | 覆盖入口/面板互斥、关闭功能域后 slider 禁用、一个参数状态变化和重置；已有客户 UI 时按其等价状态断言 | 连续拖动无黑屏/明显积压；前→后→前切换无过渡镜像错误；验证三类效果可正常生效 |
| makeup-suite/makeup/compose-makeup | `makeup-suite` 必须覆盖妆容和九类单妆且第一类为妆容；单妆按分类选择、跨分类叠加、分类清除/全部清除、A→B→A→B；声明并覆盖互斥或“组合妆基底 + 单妆覆盖”语义；仅选择组合妆时 `NveMakeup` 不得被单妆状态关闭；仅当产品提供强度控件时测试强度 | 已缓存单妆和组合妆切换无秒级延迟；组合妆的口红/眼影/腮红等至少一个彩妆项确实生效；单妆覆盖清除和组合妆切换符合已声明恢复规则 |
| filter | 选择、强度、“无”；选“无”后强度控件不存在；A→B→A→B、动态/大素材→无、动态/大素材→其他滤镜均更新到最终状态 | 不能误删其他 owner 的 filter；确认首个新代际帧已经显示，旧帧不残留或回灌 |
| face-prop | 独立 panel、“无”、A→B→A→B、无强度控件、应用成功后更新选中态/提示、失败保留原状态、收起或切换其他 panel 后状态保持 | 提示、手势/avatar/遮挡按素材能力验证；切摄像头后道具仍正确跟踪 |
| segmentation | 开关、背景选择、移除 | 快速移动边缘、前后摄方向 |
| custom animated sticker | 添加、重复选择、移除；不清空其他 custom effect | 与滤镜/道具叠加及媒体时间线 |
| recording output（请求包含录制时） | 复用既有录制状态机；连续完成两次录制；先 `markAsFinished` 再 `finishWriting`；文件可读且非空；视频源 PTS 严格单调；预览丢帧/flush 不影响录制；完成提示自动消失 | 有音频时确认 A/V 同步，无音频时确认明确接受 video-only；用文字或非对称画面验证前后摄成片镜像；按产品规则验证录制中切摄像头 |
| render/lifecycle | 初始 typed state 在首帧前提交；至少一帧成功、错误可见、output 回收、重建不崩溃 | 连续运行观察帧率/内存趋势 |

对于视觉变化，优先断言客户已有 typed state、SDK 参数或稳定截图基线。不要把“按钮被点击”当作效果已应用，也不要使用易抖动的全屏像素完全相等断言。

完整美颜只新增以下高风险回归，不把封面尺寸、tab 样式、具体间距数值等视觉细节写成自动化断言：

1. 连续拖动一个 slider 3–5 秒，确认无持续黑屏闪烁、最终 typed state 与最后输入值一致，并记录状态提交到首个新状态显示帧没有持续积压。
2. 连续执行前→后→前摄像头切换，使用非对称画面确认没有旧帧套用新镜像方向的短暂左右颠倒。
3. 启动后不触碰任何 slider，确认 UI 初始值与首个有效 NVE 帧的 applied state 一致；非零默认值不能等到首次交互才生效。
4. 只有采用 skill 默认 UI 时，断言底部入口与面板在同一底部容器中互斥切换、面板外空白点击可关闭、面板内无专用收起或关闭按钮、入口栏与所有面板复用同一底部间距来源、没有项目 spacing token 时采用 `10 pt` 默认基线、功能域关闭后 slider 不可操作，并逐项执行 `default-ui.md` 的“固定控件与层级”和“默认主题”断言；存在已授权且可读的 `coverImage`/`selectedCoverImg` 资源时，断言默认态和选中态使用对应资源而非回退图标。用项目已有 snapshot、Preview 或布局断言覆盖共享底栏的等宽入口、单行标题和已声明近期入口容量，不断言任何底栏入口的先后顺序。

默认道具 UI 额外断言：列表第一项为“无”、不存在强度 slider、A/B 已缓存切换不重新安装；注入一次素材安装或 prop 创建失败，确认原道具、原选中态和原提示不变。提示为空时断言提示区隐藏，不要求伪造文案。

异步输出所有权、output 恰好回收一次、仅用于预览的容量为 1 mailbox、`alwaysDiscardsLateVideoFrames`、slider 路径不刷新显示层以及 package/license 配对优先放在静态验证，不增加脆弱 UI 用例。请求包含录制时再执行录制行，不把它扩展成所有效果接入的默认验收负担。

对美妆切换性能，按同一个 `switchEventId` 记录素材缓存命中、状态提交、首个新状态渲染帧和首个新状态显示帧；只记录切换事件，不逐帧刷生产日志。产品可按目标设备定义阈值，但已缓存 A/B 来回切换若稳定出现 2–5 秒间隔必须判为失败。证据还应确认切换时没有再次安装素材、没有重复绑定同一 `NveMakeup`、组合妆 A→B 没有中间 `composeMakeup = nil`、没有全量清空九类单妆、没有 Main Thread Checker 警告及持续资源错误。

组合妆回归必须从“无单项美妆”状态开始选择一套同时包含美妆和滤镜/美颜的妆容，证明 compose 赋值后的最终状态仍保持 `NveMakeup` 启用，并通过 SDK 参数、typed state 或稳定截图证明口红、眼影、腮红等至少一个彩妆项生效。只看到滤镜或美颜变化不能判为组合妆通过。再执行“组合妆 → 无”和 A→B→A→B，确认清除/切换不会由单妆 enable 逻辑覆盖组合妆状态。

同时提供组合妆和单妆时，再按已声明产品语义执行回归。互斥模式分别验证“单妆 → 组合妆”和“组合妆 → 单妆”只保留目标模式；覆盖模式执行“组合妆 A → 单妆覆盖一个分类 → 清除该覆盖 → 组合妆 B”，逐步断言 compose selection、单妆分类 selection、`NveMakeup.enable` 和最终画面/SDK 参数。清除覆盖后必须按声明结果恢复组合妆该部位或保持为空，不能接受由写入顺序随机决定的结果。

采用 skill 默认完整美妆 UI 时，按 [默认效果 UI](default-ui.md) 的“完整美妆面板”契约执行全部布局与交互断言，不得因缺少其他外部输入而降低这些断言。

使用 manifest 时增加数据回归：正常条目生成名称、封面和 package 选项；空 package 条目只执行分类清除；缺失 package、无效组合妆目录、绝对路径和 `..` 越界路径均不得改变当前选中态或当前效果。不要把固定素材数量、UUID 或 manifest 顺序写进断言。

对素材滤镜使用同样的事件分段，并额外覆盖动态/大素材→无、动态/大素材→其他滤镜和快速 A→B→无。测试中延迟 A 的安装完成回调，先提交 B 或“无”，再释放 A 回调；断言 A 最多写入缓存，不能重新成为 selected/applied state 或追加到 container。断言 owner/container 状态只能证明效果链已提交；必须再证明首个新代际帧已显示。已缓存路径不得再次调用安装，显示层也不得重新展示旧代际帧。

## 运行环境阻塞

出现以下情况时继续完成静态/编译层，然后明确报告未执行层及恢复路径：

- 供应方 framework 只有 iPhoneOS slice：需要签名真机和 device destination。
- 没有 Bundle-ID 匹配授权：从美摄技术支持/商务取得授权。
- 没有目标模型/素材/素材证书：按专项门禁清单提供。
- scheme 没有测试 action 或 UI test target：复用/新增最小测试 target，或由用户接受人工 smoke。
- 相机在模拟器无可靠输入：使用项目已有测试视频/图片注入；没有注入点则转真机。

## 结果报告

交付时固定报告：

```text
静态验证：通过/失败（命令与关键结果）
编译：通过/失败（container、scheme、destination）
启动/UI：通过/失败/未执行（测试标识或阻塞原因）
真机效果/性能：通过/失败/未执行（设备、输入、功能）
剩余风险：仅列没有被上述证据覆盖的风险
```

采用默认 UI 时在结果中追加 `主题：客户主题映射/<映射标识>` 或 `主题：nve.default-theme.v1`，并记录共享主题来源断言。保留 `.xcresult`、测试日志或性能摘要的本地路径；不要提交包含客户隐私帧或授权内容的产物。
