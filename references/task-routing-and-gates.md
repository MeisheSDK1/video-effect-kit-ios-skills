# 任务路由与专项条件门禁

## 目录

- [先分类再执行](#先分类再执行)
- [授权与搜索边界](#授权与搜索边界)
- [门禁触发矩阵](#门禁触发矩阵)
- [功能 profile](#功能-profile)
- [美妆接入范围映射](#美妆接入范围映射)
- [美颜接入范围选择](#美颜接入范围选择)
- [功能 Profile 速查](#功能-profile-速查)
- [门禁输出标准](#门禁输出标准)
- [依赖获取路径](#依赖获取路径)

## 先分类再执行

先把请求归入一个稳定任务类型。分类不清且会改变依赖清单时，只问一个最小问题；不要默认执行完整门禁。

| 任务 ID | 判定标准 | 典型请求 |
| --- | --- | --- |
| `first-integration` | 客户工程还没有可用的 NveEffectKit 基础链路 | “把美颜接入现有相机” |
| `add-feature` | 授权、单例和渲染链已存在，现在新增一种效果 | “已有美颜，再加道具” |
| `repair` | 修复已有接入的错误、崩溃、无效果、方向或交互问题 | “滤镜第二次点不生效” |
| `optimize` | 不改变产品功能，降低帧耗时、内存、卡顿或启动耗时 | “优化美颜性能” |
| `upgrade` | 更换 NveEffectKit/core SDK/模型/素材版本 | “升级到新版 SDK” |
| `audit` | 只检查、解释或给出报告，不修改接入 | “审计当前生命周期” |

`add-feature` 若没有检测到 NveEffectKit 基础链，自动提升为 `first-integration`。功能修复中若发现 Bundle Identifier、SDK 版本或 core 变体已变化，只重开受影响的基础门禁，不全量重跑无关项。

## 授权与搜索边界

门禁必须区分两类输入：

1. `--project-root`：用户指定的客户项目。仅用于读取源码、工程配置、target、帧链和已有 API 接入状态，以便分类和设计最小改动。
2. 商业依赖输入：framework、core SDK、SDK `.lic`、模型、效果素材和素材证书。只能使用用户明确给出的精确路径，或在用户明确给出的 `--sdk-root`/`--resource-root` 中查找。

必须遵守：

- 不得把当前工作目录、工作区根、仓库根或 `--project-root` 自动加入商业依赖搜索范围，即使它们看起来可能包含所需文件。
- skill 独立分发时不得通过当前工作目录、环境变量或 `__file__` 的父目录推导外部工程、SDK 或资源位置；除 skill 自带文件外，每个访问根都必须来自本次用户明确输入。
- 任何外部工程都不是普通接入 profile 的隐含输入。用户未明确提供时不搜索、不等待；实现语义由本 skill 的 reference/template 完整给出。reference 未覆盖的高风险语义必须保持阻塞并索取客户公共头文件或供应方契约，不能自由推断。
- 用户明确把项目目录本身作为 `--sdk-root` 或 `--resource-root` 提供时，才可在该目录搜索对应依赖；这是单独的显式授权。
- 精确路径不存在、不可访问，或授权根目录中没有目标文件时，门禁保持阻塞，向用户列出文件名/类型、用途、阻塞原因和获取路径，然后等待用户提供；不得继续扩大搜索范围。
- 授权根目录中发现多个 `.lic` 或素材候选，只能输出 `confirm` 并请求用户选择精确路径。文件存在不能证明 Bundle Identifier 或素材证书配对正确。
- `--existing-model <文件名>` 只用于 `add-feature`：仅当用户明确确认该模型已由现有基础链接入并初始化时使用。不得根据工作区中出现同名文件自行添加。
- `repair`、`optimize`、`audit` 默认不搜索商业依赖；只有复现或验证明确需要某项依赖时，才请求该项精确路径或专项授权根目录。

## 门禁触发矩阵

| 任务 | 执行什么门禁 | 何时阻塞 |
| --- | --- | --- |
| `first-integration` | 完整基础门禁 + 请求功能门禁 | framework/core 不配对、SDK 授权缺失、最低系统不兼容、必需模型/目标素材缺失 |
| `add-feature` | 只检查新增功能的增量模型、素材和证书 | 新功能的硬依赖缺失；不要重复要求已工作的 SDK 授权 |
| `repair` | 默认不做接入门禁；先复现和定位 | 只有复现或验证确实需要缺失资源时才列出专项清单 |
| `optimize` | 默认不做资源门禁；先建立性能基线 | 缺少可运行设备、真实输入或性能采样权限时阻塞测量，不阻塞代码阅读 |
| `upgrade` | 新交付包 + `audit_vendor_drop.py` 漂移审计 | 没有新版交付包、SDK/core 配对不明或公共 API/平台漂移未处理 |
| `audit` | 只读检查，无资源门禁 | 只有用户要求运行时结论且环境不可运行时声明验证阻塞 |

执行命令：

```text
python3 -B <skill>/scripts/preflight_gate.py \
  --project-root <项目根目录> \
  --task <任务ID> \
  --features <逗号分隔的功能profile> \
  [--nve-framework <明确NveEffectKit路径>] \
  [--core-sdk <明确core SDK路径>] \
  [--sdk-root <用户授权的SDK搜索根目录>] \
  [--resource-root <用户授权的模型/素材搜索根目录>] \
  [--sdk-license <客户SDK授权路径>] \
  [--model <明确模型路径>] [--existing-model <已确认初始化的模型文件名>] \
  [--beauty-control <具体美颜控件ID>] \
  [--asset <目标素材路径> --asset-license <配套素材证书路径>] \
  [--asset-capability <none|face|fake-face|avatar|eyeball|background|hand|advanced-beauty>] \
  [--effect-id <内建滤镜ID>] \
  [--compose-root <已解压妆容目录>] \
  [--prop-capabilities fake-face,avatar,eyeball,hand,background]
```

`--resource-root`、`--model`、`--existing-model`、`--beauty-control`、`--asset-capability`、`--asset` 和 `--asset-license` 可重复，也可在单个 control/capability 参数内用逗号分隔。`--prop-capabilities` 仅为兼容旧调用的别名；旧 `--asset-capabilities-confirmed` 不能单独让门禁通过。对于需要能力清单的条件素材，确认不需要附加检测能力时必须显式传 `--asset-capability none`；`filter-builtin` 和 `filter-package` 不适用此门禁，不要求传该参数。退出码：`0` 表示可继续，`1` 表示需要最小确认，`2` 表示硬依赖阻塞。脚本只检查用户明确授权范围内的文件存在性和工程文本，绝不读取 `.lic` 内容。

## 功能 profile

先选择精确 profile，再加载功能参考。不要用含糊的“滤镜”“微整形”跳过素材类型差异。

| Profile | 必需模型 | 额外输入 |
| --- | --- | --- |
| `beauty-suite` | 展开为 `beauty-skin-suite` + `shape` + `micro-shape-package` | 完整美颜大模块；默认包含高级美肤 |
| `beauty-skin-suite` | 展开为 `beauty` + `beauty-advanced` | 完整美肤功能域；要求 `advancedBeauty` |
| `beauty` | face、faceCommon | 基础美肤（磨皮/美白/红润等）无 package |
| `beauty-advanced` | face、faceCommon、advancedBeauty | GAN/高级磨皮需目标设备验证 |
| `beauty-lut` | face、faceCommon | 客户提供 `.mslut` |
| `shape` | face、faceCommon | 目标 `.facemesh` + 配套素材 `.lic` |
| `micro-shape` | face、faceCommon | 仅内建参数；先确认目标项不依赖 package |
| `micro-shape-package` | face、faceCommon | 完整微整形同时要求 `.facemesh` 与 `.warp`；自定义具体项目只要求属性映射的类型；各自配套 `.lic` |
| `makeup-suite` | 展开为 `makeup` + `makeup-eyeball` + `compose-makeup` | 完整美妆：组合妆容、九类单项美妆和美瞳 |
| `makeup` | face、faceCommon | 目标 `.makeup` + 配套 `.lic` |
| `makeup-eyeball` | face、faceCommon、eyeball | 美瞳 `.makeup` + 配套 `.lic` |
| `compose-makeup` | face、faceCommon；按包补充 | 已解压的组合妆容目录；按内容增加 advancedBeauty/eyeball 等 |
| `filter-builtin` | 无 | 明确的内建 effect ID |
| `filter-package` | 无 | 目标 `.videofx` + 配套 `.lic`；不要求素材能力确认 |
| `face-prop` | face、faceCommon；按能力补充 | 目标 `.arscene` + 配套 `.lic` + 能力说明 |
| `segmentation` | background（small 或 medium 二选一） | 背景图/纹理与产品的分割模式 |
| `custom-effect-animated-sticker` | 默认无；按素材能力补充 | 目标 `.animatedsticker` + 配套 `.lic`；通过 core SDK 创建 effect 后放入 `customEffectArray` |

`beauty-skin-suite`、`beauty-suite` 和 `makeup-suite` 是虚拟组合 profile；门禁、静态验证和验收必须先展开成原子 profile。前两个默认包含已验证流程中的高级美肤，所以需要 `advancedBeauty`，但不因此加载 LUT、美妆、道具或其他无关模型。`makeup-suite` 固定包含组合妆容、九类单项美妆和美瞳；组合妆容仍须按实际目录能力补充模型。自定义具体项目才按单项最小映射决定依赖。

## 美妆接入范围映射

- 用户明确说“完整美妆”“全量美妆”“全部美妆功能”时，直接映射为 `makeup-suite`，不得只接 `makeup`，也不得省略组合妆容或美瞳。
- `makeup-suite` 的产品范围固定为一个独立美妆模块，包含“妆容”以及口红、眼影、眉毛、睫毛、眼线、腮红、提亮、修容、美瞳九类单项。
- 用户只说“美妆”且上下文没有“完整/全量”含义时，优先从现有产品配置和素材清单判断；只有 `makeup` 与 `makeup-suite` 的选择会改变依赖且仍无法判断时，才问一个最小范围问题。
- skill 的正确执行只依赖 skill 自带资源、客户工程以及用户明确提供或授权的输入。默认 UI、状态机、切换顺序和验收标准以本 skill 的 reference 为完整事实来源。

## 美颜接入范围选择

`first-integration` 或 `add-feature` 只笼统要求“接入美颜”“增加美颜功能”等、没有明确功能域或具体项目时，才把范围选择作为修改前的阻塞型交互门禁。允许先只读项目源码和配置，以完成任务分类并判断现有产品是否已经表达范围；只读检查不得搜索商业依赖。仍无法确定时，用结构化用户选择工具在一个弹窗中展示以下五个互斥选项。获得选择前，不运行 `preflight_gate.py`、不搜索商业依赖、不修改代码。

用户已经明确选定“完整美颜”“美肤”“美型”“微整形”，或已经列出磨皮、美白等具体项目时，范围已经成立，必须直接映射并继续，不得再次弹出范围选择。明确指定多个功能域或具体项目的组合时，直接取对应 profile/控件的并集。只有范围不明确时才执行一次选择，例如用户列出“完整美颜或美肤”等多个备选项但没有选定，或请求仍只有笼统“美颜”。

| 可选项 | 说明 | 后续 profile |
| --- | --- | --- |
| 完整美颜 | 接入美肤、美型、微整形三个完整功能域 | `beauty-suite`，再展开为原子 profile |
| 美肤 | 接入完整美肤功能域（基础与高级美肤） | `beauty-skin-suite` |
| 美型 | 接入完整美型功能域 | `shape` |
| 微整形 | 接入完整微整形功能域 | `micro-shape-package`；按 3.16.1 映射自动识别 `.facemesh`/`.warp` 依赖 |
| 自定义具体 | 只接入用户列出的磨皮、美白等具体项目；选择器必须在本次提交中收集项目列表 | 将每个项目映射到 `beauty`、`beauty-advanced`、`beauty-lut`、`shape`、`micro-shape` 或 `micro-shape-package` 的最小集合 |

交互规则：

- 先判断请求是否已有明确范围；明确范围直接执行，以下弹窗规则只适用于范围不明确的请求。
- 选项使用用户可理解的产品名称，说明中明确范围和依赖影响；不要只展示 profile ID。
- 五个选项必须一次性展示，不得把美型、微整形或自定义具体拆成第二层选择。若结构化工具无法在一个弹窗中容纳五项，使用同一个问题一次性列出五个编号选项，不得改为级联提问。
- “自定义具体”必须把具体项目作为同一次提交中的必填输入；例如“磨皮、美白”。未填写时保持当前选择未提交，不先接受选项再二次追问。
- 根据用户原始措辞和现有产品上下文排序或标记推荐项，但不得预选、代选或在超时后自动继续。
- 若用户已在自然语言中明确范围，或已经在本轮对话的弹窗中完成选择，直接复用结果，不重复弹出。
- 能一次展示五项并在同次提交中收集自定义项目的结构化工具可用时，不用普通文本问题替代；否则列出完全相同的编号选项并等待用户回复。
- 选择后从公共头文件和 [baseline-3.16.1.json](baseline-3.16.1.json) 自动判断属性、profile、模型和素材类型，不再询问功能细分。依赖文件或路径缺失时仍按门禁请求，但这不属于二次功能选择。
- `repair`、`optimize`、`upgrade`、`audit` 默认跳过该弹窗；若同一请求还要求新增或重新定义美颜范围，则只对新增范围执行选择门禁。
- “自定义具体”按基线中的控件映射一次性确定最小 profile：基础磨皮、普通美白、红润、去油光、锐化、清晰度为 `beauty`；高级/GAN 磨皮、法令纹、黑眼圈、亮眼、美牙为 `beauty-advanced`；LUT 美白为 `beauty-lut`；美型和微整形按属性映射对应 `.facemesh`/`.warp`。选择提交后不再二次询问细分。

若用户只说“滤镜”，先从现有产品配置或素材扩展名判断 `filter-builtin`/`filter-package`；仍无法判断时再问。用户选择“微整形”后直接接入完整微整形功能域，从 3.16.1 映射自动判断 package 类型，不再确认具体微整形项。

道具和动画贴纸不能无脑初始化全部模型。优先读取素材能力元数据；无法读取时请求供应方能力说明或让客户明确 `face`、`fake-face`、`avatar`、`eyeball`、`background`、`hand`、`advanced-beauty` 或 `none`。未知能力必须保持阻塞。内建滤镜和 `.videofx` 素材滤镜不依赖额外检测模型，不读取或索取素材能力清单。`--asset-capabilities-confirmed` 已废弃，不能为了让条件素材门禁变绿而添加。

## 功能 Profile 速查

| 请求能力 | 选择的 profile | 功能参考 |
| --- | --- | --- |
| 完整美颜大模块：美肤、美型、微整形 | `beauty-suite` | `beauty-and-shaping.md` |
| 美肤面板：基础/高级磨皮、美白/LUT | `beauty` / `beauty-advanced` / `beauty-lut` | `beauty-and-shaping.md` |
| 单独美型、微整形 | `shape` / `micro-shape` / `micro-shape-package` | `beauty-and-shaping.md` |
| 完整美妆：组合妆容、九类单妆、美瞳 | `makeup-suite` | `makeup-filter-prop.md` |
| 美妆、组合妆容、美瞳 | `makeup` / `compose-makeup` / `makeup-eyeball` | `makeup-filter-prop.md` |
| 内建/素材滤镜 | `filter-builtin` / `filter-package` | `makeup-filter-prop.md` |
| ARScene 人脸道具 | `face-prop` | `makeup-filter-prop.md` |
| 背景替换 | `segmentation` | `makeup-filter-prop.md` |
| animated sticker/custom effect | `custom-effect-animated-sticker` | `makeup-filter-prop.md` |

拍照、录制、闪光灯、变焦、曝光和相机切换属于客户媒体链能力，不是 NveEffectKit 效果 API。本 skill 将效果接到客户已有媒体链；若用户单独要求改造相机能力，按客户现有媒体架构处理，不把它误判成 NVE 资源门禁。

## 门禁输出标准

阻塞时在修改代码前向用户输出以下四项：

1. `任务分类`：请求类型和所选功能 profile。
2. `已确认`：从项目源码/配置确认的接入状态与帧链，以及用户明确提供或授权搜索范围内确认的依赖；不得把项目树中偶然发现的商业文件列为已确认。
3. `缺失清单`：逐项列出文件/目录、为何该功能必需、是否硬阻塞。
4. `获取路径`：从客户交付包、内容管理系统或美摄技术支持/商务取得；授权必须说明 Bundle Identifier 绑定。

不要笼统写“资源不全”。示例：

```text
任务：add-feature / face-prop
已确认：已有 NveEffectKit + NvStreamingSdkCore 基础链，SDK 授权不重复检查
阻塞：目标 .arscene 与配套素材 .lic 未提供，无法安装并验证道具
待确认：该道具是否需要 hand/avatar/background 模型
获取：客户素材交付/内容系统；缺失时联系美摄技术支持或商务获取同版本素材、证书和能力说明
下一步：等待客户提供精确文件路径，或明确授权一个可访问的素材搜索根目录
```

不读取、不打印、不提交授权内容。不得以 demo 的 `meishesdk.lic` 或 demo 素材替代客户文件。

## 依赖获取路径

| 依赖 | 合法来源 | 不允许 |
| --- | --- | --- |
| NveEffectKit + core SDK | 客户已购 SDK 交付包；美摄技术支持或商务提供匹配变体 | 从其他项目拼接二进制、只换头文件 |
| SDK `.lic` | 美摄按客户 Bundle Identifier 签发 | 复用 demo/其他 Bundle ID 授权 |
| 模型 | 与客户 SDK 同版本的模型资源包 | 用相近文件名或旧文档模型替代 |
| 效果素材 + 素材 `.lic` | 客户内容系统、已购素材交付、美摄技术支持或商务 | 只提供 package、不提供对应证书；跨版本混配 |
| 妆容目录 | 供应方已解压交付或客户受控解压目录 | zip 路径、单个 makeup 文件冒充组合妆容 |
