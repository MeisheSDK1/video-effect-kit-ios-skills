# 美妆、妆容、滤镜、道具与背景分割

## 目录

- [完整美妆固定契约](#完整美妆固定契约)
- [单项美妆](#单项美妆)
- [组合妆容](#组合妆容)
- [滤镜](#滤镜)
- [人脸道具](#人脸道具)
- [背景分割和替换](#背景分割和替换)
- [自定义特效与动画贴纸](#自定义特效与动画贴纸)
- [素材安装统一规则](#素材安装统一规则)
- [移除和状态恢复](#移除和状态恢复)
- [模型与验证](#模型与验证)

## 完整美妆固定契约

用户要求“完整美妆”“全量美妆”或“全部美妆功能”时使用 `makeup-suite`，范围不可裁剪：

1. 组合妆容，产品分类名为“妆容”。
2. 九类单项美妆：口红、眼影、眉毛、睫毛、眼线、腮红、提亮、修容、美瞳。
3. `makeup-suite` 展开为 `makeup + makeup-eyeball + compose-makeup`；组合妆目录声明的额外能力继续叠加到模型门禁。

本契约是可独立分发的完整事实来源。实现和验收只使用本 skill、客户工程以及用户明确提供或授权的输入，不把任何其他工程作为隐含依赖；必须稳定得到本文规定的功能范围、默认 UI、状态语义和切换性能行为。

修改代码前先建立资源清单：组合妆目录，以及九类单妆各自至少一个可应用的 `.makeup` 和配套 `.lic`。清单必须记录分类、稳定素材 ID、展示名、封面、package 路径和证书路径；路径进入目标资源构建阶段后再判为可用。任一分类只有“无”而没有实际素材时，不能宣称完整美妆已接入；应把该分类和缺失文件列为硬阻塞。素材数量、UUID 和目录版本继续由 manifest/资源扫描驱动，不写死在 UI。

默认 typed state 至少分开保存：

- `composeSelection`：当前组合妆或 `none`。
- `singleSelections`：按九个稳定分类分别保存当前单妆或 `none`。
- `preparedComposeByID`、`installedPackageIDByAsset`：交互前准备好的组合妆对象和真实 package ID 缓存。
- `appliedGeneration`：用于拒绝晚到的安装/创建结果，避免旧选择覆盖新选择。

客户没有给出互斥规则时，完整美妆固定采用“组合妆基底 + 单妆覆盖”。先应用组合妆，再按“口红→眼影→眉毛→睫毛→眼线→腮红→提亮→修容→美瞳”的稳定顺序重放已选单妆；不得从 SDK 对象反推产品 selection。

## 单项美妆

`NveMakeup` 支持九类单项美妆。公共头文件声明强度范围 `0...1`、默认值 `1`；产品通常应显式设置强度，避免依赖默认值。

实时 UI 状态提交、摄像头切换，以及预览、录制、RTC/直播输出复用 `realtime-state-and-output.md` 的共享契约；本文件只定义美妆、滤镜、道具和分割各自的 module adapter 语义，不为每个模块新建 capture/render/output 模板。

| 强度属性 | package ID 属性 | color 属性 | 功能 |
| --- | --- | --- | --- |
| `lip` | `lipPackageId` | `lipColor` | 口红 |
| `eyeshadow` | `eyeshadowPackageId` | `eyeshadowColor` | 眼影 |
| `eyebrow` | `eyebrowPackageId` | `eyebrowColor` | 眉毛 |
| `eyelash` | `eyelashPackageId` | `eyelashColor` | 睫毛 |
| `eyeliner` | `eyelinerPackageId` | `eyelinerColor` | 眼线 |
| `blusher` | `blusherPackageId` | `blusherColor` | 腮红 |
| `brighten` | `brightenPackageId` | `brightenColor` | 提亮 |
| `shadow` | `shadowPackageId` | `shadowColor` | 修容/阴影 |
| `eyeball` | `eyeballPackageId` | `eyeballColor` | 美瞳 |

应用流程：

1. 安装 `.makeup`，类型为 `NvsAssetPackageType_Makeup`。
2. 缓存并复用真实 package ID；不要在每次点击时重新安装。
3. 会话内只创建一个 `NveMakeup`，并只在首次创建时绑定到 `kit.makeup`。
4. 切换时只修改同一对象对应分类的 package ID、强度和可选颜色。

```objective-c
NveMakeup *makeup = kit.makeup;
if (!makeup) {
    makeup = [[NveMakeup alloc] init];
    kit.makeup = makeup; // 只绑定一次；素材切换时不要重复执行
}
makeup.lipPackageId = packageId;
makeup.lip = intensity;
makeup.lipColor = color; // 仅在产品允许覆盖素材颜色时设置
```

同一类型切换素材时替换 package ID，不要创建多个彼此不可见的 `NveMakeup`，也不要反复执行 `kit.makeup = makeup`；部分版本会把重复绑定视为效果链重建，表现为每次切换都延迟数秒。每个分类最多保留一个选中单妆，不同分类共享同一 `NveMakeup`，因此可以叠加。取消时只清除当前分类的 package ID/强度；“清除全部”才重置所有分类。

强度控件由产品交互决定，不是 SDK 接入的强制 UI。产品要求“点击即应用、无滑块”时，点击具体单妆后直接使用产品默认强度（通常为 `1`），仍要在 typed state 中记录分类与 package ID。

3.16.1 调试环境中，`NveMakeup` 的 package 属性读写可能被 Main Thread Checker 标记为需要主线程。只有出现该证据时才切换提交线程：先设置 mutation gate 让新帧丢弃，再 `DispatchQueue.main.async` 执行短属性变更，完成后 `renderQueue.async` 更新 applied state 并解除 gate。禁止从 render queue 调用 `main.sync`，也禁止主线程同步等待 render queue；这两个方向都可能死锁。素材解析和安装仍在帧外完成，不能搬到主线程逐次执行。

## 组合妆容

组合妆容不是单个 `.makeup` 文件，而是按供应方规则组织并已解压的目录，可能同时包含美颜、美型、微整形、美妆和滤镜状态。

```objective-c
NveComposeMakeup *compose =
    [NveComposeMakeup composeMakeupWithPackagePath:unpackedDirectory];
if (!compose) {
    // 返回妆容目录无效，不覆盖当前状态
}
compose.intensity = intensity; // 0...1
kit.composeMakeup = compose;
```

规则：

- 传入解压后的目录，不传 zip 文件或单个 makeup 文件。
- 在创建对象前递归解析 JSON：出现 `Advanced Beauty Enable`、`Advanced Beauty Type` 或 `Advanced Beauty Intensity` 时增加 `advancedBeauty`；出现 `Makeup Eyeball Package Id` 或 Eyeball 类型时增加 `eyeball`。3.16.1 已验证的六个基线组合妆容都命中 `advancedBeauty`，其中粉黛妆还命中 `eyeball`；新素材仍必须逐包解析，不能按名称猜能力。
- 只有命中上述已审计能力键才算元数据已识别。JSON 不可读、仅包含无关字段或未覆盖供应方声明的能力时保持门禁阻塞，索取明确能力清单；明确无附加能力时使用 `none`，不能只用一个“已确认”布尔值放行。
- 创建失败时保留旧状态，除非用户动作明确是“清除妆容”。
- `composeMakeupInnerFilters` 是只读内部滤镜集合，不应由外部直接修改。
- 使用 `NveComposeMakeupApplyDelegate.composeMakeupWillApply` 在应用前做必要的状态快照/清理；delegate 是 weak，owner 必须存活。
- 组合妆容可能改写多个功能域。应用后刷新客户自己的 typed state；移除时按产品语义恢复应用前快照或统一默认值。
- `kit.composeMakeup = compose` 可能把口红、眼影、腮红等组合项加载到同一个 `kit.makeup` 并启用它。组合妆处于激活状态时必须保持 `NveMakeup` 启用；赋值后不得再只根据“是否存在单项美妆”执行 `makeup.enable = false`。需要显式写入 enable 时，条件必须同时包含“存在单项美妆或组合妆激活”，否则会出现只剩美颜、美型或滤镜、彩妆主体缺失的不完整妆容。
- 调整组合妆容强度只修改同一 compose 对象，不重新解析目录。

用户没有指定设计且工程没有现有效果面板时，完整美妆统一执行 [默认效果 UI](default-ui.md) 的“完整美妆面板”契约；本文件只维护 SDK 对象、状态和切换语义。

组合妆与单项美妆同时存在时，先选择并记录一种产品语义，不能让属性写入顺序偶然决定结果：

- **互斥**：选择组合妆时清除单妆选择；选择任一单妆时移除组合妆。每次切换前保存需要恢复的状态，UI 与 SDK 状态在同一帧提交中一起更新。
- **组合妆基底 + 单妆覆盖**：完整美妆的默认语义。typed state 分别保存 `composeSelection` 和按分类保存的 `singleSelections`，组合妆先应用，单妆再只覆盖对应分类。切换组合妆 A→B 时直接赋值已准备好的 B，禁止先赋 `nil`；随后按稳定分类顺序重放仍保留的单妆覆盖。
- 默认覆盖模式下，清除某个单妆表示恢复当前组合妆的该部位：只把该分类 selection 改为 `none`，再直接重放当前组合妆并重放其余单妆覆盖。当前没有组合妆时才把该分类 package ID/强度清空。客户明确要求“覆盖清除后保持为空”时才替换此默认语义。
- “组合妆 → 无”只移除组合妆基底，再按产品语义保留、恢复或清除单妆覆盖；不得无条件清空全部 `NveMakeup`。全量清除是独立用户动作。
- desired、pending 和 applied state 必须使用同一套共存语义。不要只在 UI selection 中保留组合妆，却让 SDK adapter 按单妆状态计算 enable，也不要从 SDK 对象反推丢失的产品选择。

完整美妆默认状态机按以下顺序执行，不能自由改写：

1. 进入页面前解析组合妆目录、安装全部 `.makeup` 并缓存对象/package ID；交互路径只读缓存。
2. 选择组合妆 A：确认 A 已准备成功，直接执行 `kit.composeMakeup = A`，保持 `NveMakeup.enable`，再重放九类中已选择的单妆覆盖。
3. A→B：直接执行 `kit.composeMakeup = B`，不得先设 `nil`、不得先清九类单妆、不得重新解析或安装；然后仅重放仍保留的单妆覆盖。
4. 清除一个单妆覆盖：更新该分类 selection；有组合妆时直接重放当前 compose 和其余覆盖，没有组合妆时只清该分类。
5. 选择“妆容-无”：此时才执行 `kit.composeMakeup = nil`，恢复组合妆应用前的美颜/美型/微整形/滤镜快照，并按 typed state 重放仍保留的单妆。
6. “清除全部”是独立动作：清 compose、九类单妆及属于本模块的快照；不得由普通 A/B 切换或关闭面板触发。

`composeMakeup = nil → composeMakeup = B` 会先拆除再重建组合效果链，叠加九类单妆全量 reset/replay 时可形成 2–5 秒空档。该写法是切换路径禁区，不是安全的“先清后设”；`nil` 只属于明确的“妆容-无”或全量清除。

供应方提供 manifest 时使用资源驱动的选项模型：

- 名称、封面、相对 package 路径和可选分类来自 manifest；不要硬编码素材数量、UUID、目录版本或展示顺序。
- 用客户授权的资源根目录解析相对路径，标准化后确认结果仍位于该根目录内；拒绝绝对路径和 `..` 越界路径。
- 空 package 路径只表示 manifest 明确定义的“无”项，不传给 `NveComposeMakeup` 或素材安装接口。UI 也可以由产品层合成“无”，但同一分类只能有一个清除语义。
- 验证名称/封面缺失时可使用产品允许的占位显示；package 目录、素材文件或证书缺失以及组合妆创建失败时不得发布新选中态，应保留当前效果并返回可诊断错误。
- manifest 顺序仅作为供应方展示建议。产品需要调整顺序时在 UI adapter 显式排序，不修改素材 JSON，也不让顺序承担互斥、默认选中或恢复逻辑。

## 滤镜

`NveFilter` 的 `effectId` 可以是内建效果名，也可以是已安装 `.videofx` 的 package ID；`intensity` 范围 `0...1`，默认 `1`。

普通后置滤镜：

```objective-c
NveFilter *filter = [NveFilter filterWithEffectId:effectId];
filter.intensity = intensity;
[kit.filterContainer append:filter];
```

容器规则：

- `filterContainer` 位于美颜之后；`rawFilterContainer` 位于美颜之前。
- `filters` 是只读快照/数组，不要假设可变。
- 单选 UI 应先删除旧目标滤镜，再追加新滤镜；不要默认删除容器中由客户其他模块管理的全部滤镜。
- 多滤镜场景保留明确顺序和 owner 标识。`remove:` 必须传入本 adapter 持有的同一对象；丢失 owner 引用时停止清除并修复状态所有权，不能仅按 `effectId` 删除，因为其他模块可能使用相同 ID。
- “无”状态应移除目标滤镜，不创建空 effect ID，也不能只把强度设为 `0`。当没有选中滤镜时隐藏滤镜强度控件，不要显示为禁用；选择状态由“无”选项自身表达。
- 验证面板的辅助文案必须描述真实操作，不能在标题区用“无滤镜”等静态文字重复或冒充当前选择状态。
- 素材滤镜先以 `NvsAssetPackageType_VideoFx` 安装；内建滤镜不安装。
- 素材滤镜的完整可审计链是 `.videofx` + 配套 `.lic` → `VideoFx` 安装 → 非空真实 package ID → `NveFilter(effectId:)` → `filterContainer.append` → owner 持有同一对象并用 `remove:` 切换/清除；只有资源存在不能判为接入完成。

不要把 demo 的 `filters.firstObject` 当成所有工程的目标滤镜；客户可能已经有多个效果。

## 人脸道具

ARScene 道具流程：

1. 安装 `.arscene`，类型 `NvsAssetPackageType_ARScene`。
2. 初始化该素材需要的人脸及可选模型。
3. 使用 package ID 创建 `NveFaceProp`。
4. 设置 `kit.prop`。

```objective-c
NveFaceProp *prop = [NveFaceProp propWithPackageId:packageId];
if (!prop) {
    // 返回 package ID 无效
}
kit.prop = prop;
```

在 NveEffectKit 3.16.1 的 Swift 导入中，Objective-C `propWithPackageId:` 是可失败初始化器，不是 `prop(withPackageId:)`：

```swift
guard let prop = NveFaceProp(packageId: packageID) else {
    // package ID 无效；保留当前道具和已应用状态
    return
}
effectKit.prop = prop
```

相关 API：

- `getARSceneAssetPackagePrompt:`：安装成功后使用真实 package ID 获取素材交互提示；空字符串是合法结果，UI 隐藏提示区，不自行编造文案。
- `getARSceneManipulate`：获取 AR 场景操作接口。
- `getARSceneObject`：返回内部管理的 AR Scene effect；公共头文件明确建议外部不要强引用。
- `manipulateDelegate`：weak delegate；由稳定 owner 持有 delegate 实例。

在帧回调之外构造新 prop；切换时只在稳定渲染队列用新 prop 替换旧 prop。取消时设置 `kit.prop = nil`。道具可能需要手势、avatar、假脸、眼球或背景分割模型；缺少可选模型时，道具可能部分可见但交互或局部效果失效。

默认交互只在用户没有指定设计、工程也没有现有效果面板时使用：

- 提供独立“道具”底部入口和贴底面板，与美颜、美妆、滤镜等顶层面板互斥展开；点击面板外空白处收起，但不清除已应用道具。
- 面板使用横向单选素材列表，“无”固定在第一项；具体素材显示封面、名称和选中态，不显示强度 slider。
- 点击 A/B 只在准备成功后提交新 prop；A→B 直接替换，点击“无”设置 `kit.prop = nil`。切换面板、收起面板和切换摄像头不丢失已应用状态。
- 已缓存 A→B→A→B 不重新安装。按需安装时只给目标素材显示 loading；安装或 `NveFaceProp` 创建失败时保留原 prop、原选中态和原提示，并展示可诊断错误。
- 只有 prop 已在稳定渲染队列成功赋值后才发布新选中态和对应素材提示；提示为空时隐藏提示区。
- 使用 `nve.prop.entry`、`nve.prop.panel`、`nve.prop.parameter.select`、`nve.prop.clear`、`nve.prop.option.<id>`、`nve.prop.loading`、`nve.prop.error` 和 `nve.prop.prompt` 等稳定 accessibility identifier。
- 这些是产品语义与状态合同，不固定 SwiftUI/UIKit 组件、圆角、字号、图标、精确尺寸或素材排列；采用默认 UI 时，颜色、材质、边框和状态色统一执行 [默认效果 UI](default-ui.md) 的 `NVEEffectTheme` 契约。

## 背景分割和替换

3.16.1 demo 使用内建前置滤镜 `Segmentation Background Fill`：

```objective-c
NveFilter *segmentation =
    [NveFilter filterWithEffectId:@"Segmentation Background Fill"];
[segmentation setEffectParam:@"Segment Type"
                         type:NveParamType_MenuVal
                        value:@"Half Body"];
[segmentation setEffectParam:@"Stretch Mode"
                         type:NveParamType_int
                        value:@(1)];
[segmentation setEffectParam:@"Tex File Path"
                         type:NveParamType_string
                        value:backgroundImagePath];
[kit.rawFilterContainer append:segmentation];
```

可选参数示例还包括 `Detect Interval`。只有客户明确接受降低检测频率时才提高间隔，并在快速运动、遮挡和边缘场景真机验证。

规则：

- 初始化 `background` 模型。
- 背景图片在启用前加载/解析路径，不在每帧查找 bundle。
- 背景替换属于美颜前效果，放在 `rawFilterContainer`。
- 使用参数声明匹配的 `NveParamType`；`Segment Type` 是 menu value，不要随意改成 string 类型。
- 切换/关闭时移除由本功能 owner 添加的 segmentation 对象，避免误删其他 raw filters。
- 中低端设备可选择 small segmentation 模型，高端设备可选择 medium；策略应可配置并经过性能验证，不照搬过时的设备字符串阈值。

## 自定义特效与动画贴纸

`customEffectArray` 用于由匹配 core SDK 创建、但不属于 beauty/filter/prop 等专用属性的 `NvsEffect`。`.animatedsticker` 与 `.arscene` 人脸道具是不同素材类型，不能使用 `NveFaceProp` 路径接入。

流程：

1. 用 `NvsAssetPackageType_AnimatedSticker` 安装客户选中的 `.animatedsticker` 和配套素材证书，并取得真实 package ID。
2. 用与当前 NveEffectKit 配对的 core SDK context 创建 `NvsVideoEffect`；aspect ratio、start/duration 和 panoramic 参数来自客户实际媒体时间线，不复制 demo 的占位常量。
3. 将 effect 加入 `kit.customEffectArray`，并由功能 owner 保存同一对象引用。
4. 关闭或切换时用 `removeObject:` 移除 owner 的对象；不要 `removeAllObjects` 清掉其他模块的自定义效果。
5. 会话销毁前停止帧流并清理状态；数组中剩余 effect 最终由 NveEffectKit 销毁。

```objective-c
NvsVideoEffect *sticker =
    [context createAnimatedSticker:startTime
                           duration:duration
                        isPanoramic:NO
                          packageId:packageId
                         aspectRatio:aspectRatio];
if (!sticker) {
    // 返回创建失败，不修改当前数组
}
[kit.customEffectArray addObject:sticker];
```

动画贴纸是否需要检测模型由素材能力决定；没有能力说明时保持阻塞并索取供应方能力清单，不因为它叫“贴纸”就初始化全部人脸模型。若清单明确不需要附加检测能力，记录为 `none`。验收要覆盖添加、重复选择、移除，以及与普通滤镜/人脸道具同时存在时的 owner 隔离。

## 素材安装统一规则

| 能力 | 常见后缀 | 安装类型 |
| --- | --- | --- |
| 单项美妆 | `.makeup` | `Makeup` |
| 滤镜 | `.videofx` | `VideoFx` |
| 人脸道具 | `.arscene` | `ARScene` |
| 美型/微整形 | `.facemesh` / `.warp` | `FaceMesh` / `Warp` |
| 自定义动画贴纸 | `.animatedsticker` | `AnimatedSticker` |

```objective-c
NSMutableString *packageId = [NSMutableString string];
NvsAssetPackageManagerError error =
    [kit installAssetPackage:packagePath
                     license:assetLicensePath
                        type:type
              assetPackageId:packageId];
BOOL installed =
    error == NvsAssetPackageManagerError_NoError ||
    error == NvsAssetPackageManagerError_AlreadyInstalled;
```

安装前验证 package 与证书存在、类型匹配。不要打印 `.lic` 内容。失败时记录错误枚举、素材类型和经过脱敏的文件名。

素材 manifest 未显式提供证书路径时，先用匹配 core SDK 的 asset package manager 从素材文件取得真实 package ID，再按客户资源定位规则查找该 ID 对应的 `.lic`。不要通过截断 `UUID.version.arscene`、`UUID.version.videofx` 等文件名猜 package ID 或证书名；无法取得真实 ID 或唯一配套证书时保持阻塞。

`AlreadyInstalled` 也是成功。若安装输出 ID 为空，先检查客户实际 core SDK 公共头文件，再用同一个 asset package manager 从素材文件回查真实 package ID；两个 core 变体的 selector 不要互相套用，也不要猜 API。无法确认回查接口或 ID 仍为空时，保留当前效果并返回可诊断错误。缓存真实 package ID；道具 prompt、对象创建和后续切换都使用该 ID。

安装和预热策略：

- 不在 capture/render 串行队列执行交互式素材安装；“不在逐帧函数内”仍不足以避免安装任务阻塞后续帧。
- 素材集合小且已知、或包含明显较大的动态包时，可在帧流开始前预安装并缓存 package ID。
- 素材目录很大时，在独立准备队列按需预热，并向 UI 暴露加载状态；安装完成后再把短状态变更串行提交到 render 队列。
- 按需安装必须携带单调递增的 `selectionRequestID`（或等价 generation）和素材标识。安装完成后先重新核对它仍对应最新 desired selection，才能发布“已选中”并提交到 render queue；过期结果可以写入 package ID 缓存，但不得修改 UI selected state、applied state、owner 对象或 container。
- A 安装中又选择 B/“无”时，B/“无”立即成为唯一 desired state。A 的晚到成功、失败和重试回调都只能结束自身 loading 记录，不能覆盖当前错误状态或回灌 A。
- A→B→A→B 和 A→无 的已缓存路径不得再次安装。不要为了切换速度无条件预安装未知规模的完整素材库。

## 移除和状态恢复

- 美妆单项：清除对应 package ID/强度，不影响其他类型。
- 组合妆容：设置 `kit.composeMakeup = nil`，再按产品规则恢复之前的 beauty/shape/micro/makeup/filter 状态。
- 普通滤镜：从正确 container 移除 owner 对象。
- 道具：`kit.prop = nil`。
- 背景分割：从 `rawFilterContainer` 移除 segmentation 对象。
- 全量清理只在媒体会话结束或用户明确“清除全部效果”时进行，不要由某个单选控件调用 `removeAll` 清掉其他模块状态。
- 对动态滤镜可在对象级移除前把强度归零作为防御性视觉屏障，但它不是清除语义，不能替代 `remove:`；移除失败时恢复原强度并报告错误。

## 模型与验证

- 单项美妆：`face`、`faceCommon`；美瞳增加 `eyeball`。
- 组合妆容：基础为 `face`、`faceCommon`；实际解析 JSON/能力清单并补充 `advancedBeauty`、`eyeball`。无法识别时阻塞，不静默按基础模型放行。
- 内建滤镜和 `.videofx` 素材滤镜：不依赖额外检测模型，不要求 `asset-capability` 或 `none` 确认。
- 道具、动画贴纸：按素材清单映射 `face`、`fakeFace`、`avatar`、`eyeball`、`background`、`hand`、`advancedBeauty`；明确无附加检测能力时使用 `none`，未知时阻塞。
- 背景分割：`background`。

真机验证不仅看“有效果”：还要检查素材提示、手势触发、遮挡、多人脸、快速转头、背景边缘、组合妆容移除后的状态，以及重复安装后的 package ID。
