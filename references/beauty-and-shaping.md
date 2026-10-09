# 美颜、美型与微整形

## 目录

- [通用状态规则](#通用状态规则)
- [验证型 UI](#验证型-ui)
- [基础和高级美颜](#基础和高级美颜)
- [美型](#美型)
- [微整形](#微整形)
- [素材安装](#素材安装)
- [默认值与重置](#默认值与重置)
- [模型与性能](#模型与性能)
- [已知示例缺陷](#已知示例缺陷)

## 通用状态规则

- 产品层的“完整美颜”是美肤、美型、微整形三个独立功能域的组合；使用 `beauty-suite` 路由时仍分别管理三个对象的开关、参数和重置，不合并成一个 SDK 对象。
- `NveBeauty`、`NveShape`、`NveMicroShape` 都继承 `NveItem`，支持 `enable` 和底层 `setEffectParam`。
- 为每个功能域创建一个长生命周期对象并赋给 `NveEffectKit` 对应属性。slider 变化时更新同一对象，不要逐次创建新对象。
- 高频 slider 事件只更新 typed state 和一个容量为 1 的 pending latest state；在下一输入帧 render 前串行取出并差量应用。不要为每个 value event 向 render 队列追加 block，也不要在 slider 路径刷新预览层。
- 属性值先按公共头文件范围 clamp，再传入 SDK。除非产品明确要求，不照搬 demo 的非零视觉默认值。
- 开关功能优先使用该对象的 `enable`；重置功能应恢复属性和高级参数，而不是仅隐藏 UI。已审计的 shape/micro package ID 是参数实现依赖，普通重置不得清空或重新安装；只有移除 owner 或更换素材映射时才改变。
- 组合妆容会同时影响美颜/美型/微整形/美妆。应用和移除组合妆容后，应重新读取或恢复当前状态，不能假设原对象完全未变。

## 验证型 UI

按以下顺序选择 UI，不能跳过已有设计体系：

1. 用户提供视觉或交互要求：按用户要求实现。
2. 工程已有产品效果面板、设计 token、可复用组件或视觉规范：复用客户体系。
3. 两者都不存在：采用下面的默认验证 UI。

- 底部入口与编辑面板遵守 [默认效果 UI](default-ui.md) 的共享规则：两者互斥并复用同一底部间距来源；默认 UI 只通过点击面板外空白区域收起，不在面板内部增加专用收起或关闭按钮。
- 用美肤、美型、微整形三个纯文字 tab 切换功能域；不使用胶囊按钮或下划线，各域保留独立开关和重置。
- 参数使用横向“统一大小封面 + 底部文字”列表。客户已提供或授权的资源中存在可读的 `coverImage`/`selectedCoverImg` 映射及对应图片时，必须分别用于默认态和选中态，不得为图省事改用系统图标或自绘占位图。只有授权资源根目录中确实缺少映射、对应图片不可读或客户设计明确覆盖时，才使用确定性的本地图标回退并在交付报告中说明原因；不得为寻找封面扩大未授权搜索范围。默认态也必须清晰可见，不能只有选中后才出现封面。
- 一次只展示当前参数控制行：左侧只显示数值，中间 slider，右侧依次为重置、启用开关。功能域关闭时 slider 禁用。
- 默认紧凑规格以约 `48×48 pt` 封面、短间距和单行参数名为起点，再按 Dynamic Type、设备宽度和客户组件调整。
- 展开、收起和切换功能域时保持当前参数值、启用状态和已安装 package ID，不通过重建效果对象刷新 UI。
- 把相机切换放在预览右上角，把授权/初始化错误等全局状态与参数面板分开，避免增加面板常驻高度。
- 给入口、面板、空白收起层、功能域、参数选择、slider、开关和重置设置稳定的 accessibility identifier。

这是无设计输入时的默认交互契约，不得覆盖用户要求或客户已有设计体系。按工程现有 SwiftUI/UIKit 技术栈实现，不把某一套页面代码作为 SDK 通用模板。不要为了满足入口要求引入全套示例页面或大面积全屏 modal。

## 基础和高级美颜

`NveBeauty` 公共属性范围均为 `0...1`，头文件默认值为 `0`：

| 属性 | 功能 |
| --- | --- |
| `strength` | 磨皮 |
| `whitening` | 美白 |
| `reddening` | 红润 |
| `matte` | 去油光 |
| `removeNasolabialFolds` | 淡化法令纹 |
| `removeDarkCircles` | 淡化黑眼圈 |
| `brightenEyes` | 亮眼 |
| `whitenTeeth` | 美牙 |
| `sharpen` | 锐化 |
| `definition` | 清晰度 |

基础对象：

```objective-c
NveBeauty *beauty = [[NveBeauty alloc] init];
beauty.strength = 0.35;
beauty.whitening = 0.20;
kit.beauty = beauty;
```

美白 A 使用普通 `whitening`，并关闭 LUT：

```objective-c
beauty.whitening = value;
[beauty setEffectParam:@"Whitening Lut Enabled" type:NveParamType_bool value:@(NO)];
[beauty setEffectParam:@"Whitening Lut File" type:NveParamType_string value:@""];
```

美白 B 使用客户提供的 `.mslut` 路径：

```objective-c
beauty.whitening = value;
[beauty setEffectParam:@"Whitening Lut Enabled" type:NveParamType_bool value:@(YES)];
[beauty setEffectParam:@"Whitening Lut File" type:NveParamType_string value:lutPath];
```

切回普通美白时必须清空 LUT 路径，避免旧文件继续参与效果。

基础磨皮：

```objective-c
beauty.strength = value;
[beauty setEffectParam:@"Advanced Beauty Enable" type:NveParamType_bool value:@(NO)];
[beauty setEffectParam:@"Advanced Beauty Intensity" type:NveParamType_float value:@(0)];
[beauty setEffectParam:@"Beauty Strength" type:NveParamType_float value:@(value)];
```

高级磨皮：

```objective-c
beauty.strength = value;
[beauty setEffectParam:@"Advanced Beauty Enable" type:NveParamType_bool value:@(YES)];
[beauty setEffectParam:@"Advanced Beauty Type" type:NveParamType_int value:@(typeIndex)];
[beauty setEffectParam:@"Beauty Strength" type:NveParamType_float value:@(0)];
[beauty setEffectParam:@"Advanced Beauty Intensity" type:NveParamType_float value:@(value)];
```

3.16.1 demo 使用高级类型索引 `0`、`1`、`2`，GAN 设备路径还使用 `3`。高级/GAN 磨皮以及法令纹、黑眼圈、亮眼、美牙都依赖 `advancedBeauty`。完整“美肤”和“完整美颜”默认包含这些高级控件，因此开始接入前必须取得 `advancedbeauty_v1.0.1.dat`；只有自定义具体项目且全部为基础美肤时才不要求它。启用索引 `3` 后还必须在目标设备真机验证；不要只按设备名称猜测能力。

## 美型

`NveShape` 属性范围为 `-1...1`，头文件默认值为 `0`。每个属性可以配套一个 FaceMesh package ID：

| 属性 | package ID 属性 | 功能 |
| --- | --- | --- |
| `faceWidth` | `faceWidthPackageId` | 窄脸 |
| `faceLength` | `faceLengthPackageId` | 小脸 |
| `faceSize` | `faceSizePackageId` | 瘦脸 |
| `foreheadHeight` | `foreheadHeightPackageId` | 额头 |
| `chinLength` | `chinLengthPackageId` | 下巴 |
| `eyeSize` | `eyeSizePackageId` | 大眼 |
| `eyeCornerStretch` | `eyeCornerStretchPackageId` | 眼角 |
| `noseWidth` | `noseWidthPackageId` | 瘦鼻 |
| `noseLength` | `noseLengthPackageId` | 鼻长 |
| `mouthSize` | `mouthSizePackageId` | 嘴型 |
| `mouthCornerLift` | `mouthCornerLiftPackageId` | 嘴角 |

应用顺序：先成功安装 `.facemesh`，把返回的 package ID 设置到对应属性，再设置强度并把 shape 赋给 `kit.shape`。

```objective-c
NveShape *shape = kit.shape ?: [[NveShape alloc] init];
shape.faceWidthPackageId = packageId;
shape.faceWidth = value;
kit.shape = shape;
```

不要把素材文件路径直接填入 package ID 属性，也不要把 `NveBeauty` 对象误赋给 `shape`。

## 微整形

`NveMicroShape` 属性范围为 `-1...1`，头文件默认值为 `0`：

| 属性 | package ID 属性 | 3.16.1 素材类型 |
| --- | --- | --- |
| `headSize` | `headSizePackageId` | Warp |
| `malarWidth` | `malarWidthPackageId` | FaceMesh |
| `jawWidth` | `jawWidthPackageId` | FaceMesh |
| `templeWidth` | `templeWidthPackageId` | FaceMesh |
| `eyeDistance` | `eyeDistancePackageId` | FaceMesh |
| `eyeAngle` | `eyeAnglePackageId` | FaceMesh |
| `philtrumLength` | `philtrumLengthPackageId` | FaceMesh |
| `noseBridgeWidth` | `noseBridgeWidthPackageId` | FaceMesh |
| `noseHeadWidth` | `noseHeadWidthPackageId` | FaceMesh |
| `eyebrowThickness` | `eyebrowThicknessPackageId` | FaceMesh |
| `eyebrowAngle` | `eyebrowAnglePackageId` | FaceMesh |
| `eyebrowXOffset` | `eyebrowXOffsetPackageId` | FaceMesh |
| `eyebrowYOffset` | `eyebrowYOffsetPackageId` | FaceMesh |
| `eyeWidth` | `eyeWidthPackageId` | FaceMesh |
| `eyeHeight` | `eyeHeightPackageId` | FaceMesh |
| `eyeArc` | `eyeArcPackageId` | FaceMesh |
| `eyeYOffset` | `eyeYOffsetPackageId` | FaceMesh |

当前 NveBeauty 已包含法令纹、黑眼圈、亮眼和美牙，不要引用旧文档中不存在于当前 `NveMicroShape` 头文件的同名枚举分支。

微整形开关必须修改 `kit.microShape.enable`，不能误改 `kit.shape.enable`。恢复微整形值时从 `NveMicroShape` 读取，不能对 `NveShape` 调用同序号枚举。

## 素材安装

| 后缀 | `NvsAssetPackageType` |
| --- | --- |
| `.facemesh` | `NvsAssetPackageType_FaceMesh` |
| `.warp` | `NvsAssetPackageType_Warp` |

安装规则：

1. 确认 package 和配套 `.lic` 都来自客户的同一交付包。
2. 在渲染前安装，禁止在 slider/逐帧回调中反复安装。
3. 同时接受 `NoError` 和 `AlreadyInstalled`。
4. `AlreadyInstalled` 时若输出 `NSMutableString` 为空，使用匹配 core SDK 的 asset package manager 从文件取得 package ID；不要从文件名盲目截断版本号。
5. 缓存 `package path + type + SDK version → package ID`，SDK 版本或素材变化时使缓存失效。

## 默认值与重置

公共头文件默认值是可维护的安全基线。3.16.1 demo JSON 还展示了以下视觉预设，但它们不是 SDK 默认值：

- 美型：`faceLength=0.4`、`faceSize=0.36`、`eyeSize=0.26`、`eyeCornerStretch=0.1`、`noseWidth=0.45`、`mouthCornerLift=0.1`。
- 微整形：`headSize=0.3`、`malarWidth=0.2`、`jawWidth=0.15`、`noseBridgeWidth=0.3`。
- 美颜：黑眼圈 demo 值 `1.0`、亮眼 demo 值 `0.6`，其他大多为 `0`。

这些值仅在用户明确要求“与 demo 初始视觉一致”时采用，并应写成客户可配置预设，而不是散落在 UI 代码。

重置时：

- 把属性恢复到产品预设或 SDK 默认值。
- 将强度和高级参数恢复到产品预设或 SDK 默认值。已审计且仍属于本功能的 package ID 可继续绑定以便复用，不因普通 UI 重置重新安装；只有移除功能 owner 或更换素材映射时才清理对应 package ID。
- 关闭高级磨皮、LUT 等底层参数。
- 保持 `enable` 与 UI 状态一致。
- 组合妆容已应用时，先明确是恢复妆容快照还是全量清零。

## 模型与性能

- 自定义基础美肤、美型、微整形：初始化 `face` 和 `faceCommon`。
- 完整美肤、完整美颜，以及高级/GAN 磨皮、法令纹、黑眼圈、亮眼、美牙：额外初始化 `advancedBeauty`。
- LUT 美白使用客户 `.mslut`，不增加检测模型。
- 不因使用普通滤镜而初始化人脸模型。
- 模型初始化移出页面重复进入路径，并缓存每个类型的成功状态。
- 高/低规格背景模型选择只影响分割，不应用于普通 beauty 模型选择。
- 设备分级应基于经过验证的能力策略或产品配置；demo 按硬件字符串主版本判断仅是示例，不应成为长期兼容表。

## 已知示例缺陷

- `beautyEffect.json` 和 `beautyEffect_gan.json` 含尾逗号，严格 JSON 解析失败；不要复制为客户运行时配置。
- 文档的模型文件名落后于 3.16.1 实际资源。
- 文档示例把 `shape` 赋成了 `beauty`。
- demo 恢复微整形时错误读取 `defaultShap`，且微整形开关错误修改 `shape.enable`。
- 某些 demo 读取 `getEffectParam` 返回值时依赖 YYModel 内部表示。客户代码应优先持有自己的 typed state，不要把未公开的返回对象 JSON 结构当稳定 API。
- demo 的 slider delegate 立即更新现有效果对象，这一行为可作为交互语义参考；在客户工程中仍要把状态提交与 render 串行，并使用容量为 1 的 pending latest state，不能让每次 slider event 排在帧任务前。
- `coverImage`/`selectedCoverImg` 分别定义默认态与选中态封面资源；客户已提供或授权对应资源时必须使用，但不能复制外部页面实现，也不能假设其他客户一定携带相同图标。
