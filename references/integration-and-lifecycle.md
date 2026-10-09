# 集成与生命周期

## 目录

- [事实基线](#事实基线)
- [接入前检查](#接入前检查)
- [依赖与工程设置](#依赖与工程设置)
- [初始化顺序](#初始化顺序)
- [功能到模型的选择](#功能到模型的选择)
- [生命周期和错误传播](#生命周期和错误传播)
- [Swift 互操作](#swift-互操作)
- [禁止照抄的示例](#禁止照抄的示例)

## 事实基线

- 本 skill 已验证的资料版本是 NVE SDK `3.16.1.2`；工程展示版本为 `3.16.1`。
- 当前资料中的 `NveEffectKit.framework` 声明最低 iOS `12.0`，仅声明 `iPhoneOS` 平台；客户实际交付包仍需重新检查。
- NveEffectKit 会在编译期优先导入 `NvStreamingSdkCore`，否则导入 `NvEffectSdkCore`。NveEffectKit 二进制必须与实际 core SDK 由供应方成对提供，不能通过改 import 强行混用。
- NveEffectKit 是商业二进制。本 skill 不提供 framework、模型、效果素材或 `.lic`。
- SDK 授权文件绑定客户应用 Bundle Identifier。任何 demo 授权都不能复制到客户工程。
- 公共头文件和客户拿到的实际资源文件优先于接入文档中的文件名或示例。

## 接入前检查

先识别现有工程，不要直接添加一套新架构：

1. 找到 app/extension 的实际 target、workspace/project、scheme 和最低系统版本。
2. 找到当前依赖入口：手工 framework、CocoaPods、内部 pod、XCFramework 或其他公司构建系统。
3. 搜索 `NvEffectSdkCore`、`NvStreamingSdkCore`、`NveEffectKit`，确认只存在预期变体，避免重复链接或模块名冲突。
4. 找到帧入口及队列：`AVCaptureVideoDataOutputSampleBufferDelegate`、直播 SDK callback、OpenGL renderer 或单图处理入口。
5. 确认输入/输出格式、方向、镜像、下游是否异步持有帧，以及谁负责停止帧流和销毁引擎。
6. 确认客户明确提供：SDK 授权、所需模型、素材包、素材证书，以及与其 SDK 版本匹配的 NveEffectKit；每项应有精确路径，或由客户明确给出可访问的 SDK/资源搜索根目录。

项目根目录只用于理解源码和工程配置，不代表客户授权递归搜索其中的商业依赖。未提供精确路径或授权搜索根目录时，先列出缺失清单和合法获取路径并等待，不得扫描工作区或外部目录猜测文件位置。

若项目已有 NVE 接入，优先修复或扩展现有 owner，不要再创建第二套单例管理器。

## 依赖与工程设置

最低要求：

- 将 effective deployment target 设置为客户 NveEffectKit 二进制声明的最低版本或更高；3.16.1 基线不得低于 iOS 12.0。
- 将 NveEffectKit 和匹配的 core SDK 同时 Link；动态 framework 还要 Embed & Sign。
- 保留供应方要求的 `-ObjC`。如客户构建系统已继承该选项，不要重复覆盖整个 `OTHER_LDFLAGS`。
- 确保 framework 搜索路径使用项目相对路径或构建系统变量，不写开发机绝对路径。
- 仅在实际使用相机/麦克风时添加对应 Privacy Usage Description；不要由效果接入无条件添加录音权限。
- 检查 framework/XCFramework 是否包含目标设备或模拟器 slice。只有 device framework 时，不要承诺模拟器可运行。

不要把 demo 的内部 `NvEffectModule` 当成客户必须依赖。它主要提供演示 UI、view model、模型/素材组织和便利分类；客户可以直接调用 NveEffectKit 公共 API。

## 初始化顺序

授权必须发生在任何间接或直接 `shareInstance` 之前，包括会在初始化中访问单例的 view model。

Objective-C 最小顺序：

```objective-c
NSString *licensePath = /* 客户配置 */;
if (licensePath.length == 0 || ![[NSFileManager defaultManager] fileExistsAtPath:licensePath]) {
    // 返回“授权文件缺失”，不要触发 SDK
}
if (![NveEffectKit verifySdkLicenseFile:licensePath]) {
    // 返回“SDK 授权失败”，停止初始化
}

// 从基线按功能/控件/素材能力生成 requiredModels；逐类型初始化并检查。
for (NVERequiredModel *model in requiredModels) {
    BOOL ok = [NveEffectKit initHumanDetection:model.type
                                      modelPath:model.path
                                 licenseFilePath:nil];
    if (!ok) {
        // 返回对应模型类型和文件名，不包含授权内容；禁止继续获取单例
        return;
    }
}

NveEffectKit *kit = [NveEffectKit shareInstance];
```

Swift 等价原则：

```swift
guard FileManager.default.fileExists(atPath: licenseURL.path) else {
    throw NVEIntegrationError.missingLicense
}
guard NveEffectKit.verifySdkLicenseFile(licenseURL.path) else {
    throw NVEIntegrationError.licenseRejected
}
// 先逐项 initHumanDetection，再获取 shareInstance()。
```

授权结果适合由 process-wide gate 缓存。不要把授权逻辑放在每个页面或逐帧入口中。

## 功能到模型的选择

模型初始化接口可以多次针对不同类型调用，但每一类型应在进程中只初始化一次。功能 profile 与条件输入见 [task-routing-and-gates.md](task-routing-and-gates.md)，3.16.1 模型、功能和素材能力的唯一映射是 [baseline-3.16.1.json](baseline-3.16.1.json)。门禁、实现、验证和其他文档不得各自维护硬编码清单。

无法取得道具或动画贴纸能力元数据时，必须停在门禁并索取供应方能力说明；明确无附加检测能力时记录为 `none`。内建滤镜和 `.videofx` 素材滤镜不进入该能力门禁。不要以“兼容任意素材”为由复制 Demo 全量预载，也不要把“初始化全部模型”作为普通滤镜或自定义基础美颜的默认路径。

## 生命周期和错误传播

推荐由应用级或媒体会话级 owner 管理状态：

```text
uninitialized → authorized → modelsReady → running → stopping → destroyed
```

- `authorized` 之前不得访问单例。
- 所有必需模型 ready 后再接通帧流；可选模型失败时禁用对应能力并返回明确诊断。
- `running` 期间不要销毁单例。先停止/断开帧源，再等待渲染队列排空。
- 仅由创建媒体会话的 owner 调用 `destroyInstance`。若多个页面共享效果引擎，使用应用级 owner 或引用计数式会话协调，而不是在页面 `dealloc` 中直接销毁。
- 初始化失败应包含阶段、模型/素材的非敏感标识和 SDK 错误枚举；不要只 `NSLog` 后继续渲染。
- 再次创建会话时必须重新构造效果状态和 container；不要持有已销毁实例返回的效果对象。

## Swift 互操作

- 通过 framework module `import NveEffectKit`；core SDK 的公开枚举也由 NveEffectKit 头文件引入。
- 供应方 Objective-C API 未全面声明 Swift 专用名称。实际 Swift 符号以客户二进制和 Xcode 自动补全为准；遇到名称差异时不要猜测，应在 Mac 编译验证。
- `NSMutableString` 输出参数、C 枚举、`CVPixelBuffer` 和 OpenGL `GLuint` 是最易出现桥接差异的位置。
- Swift wrapper 只封装生命周期、错误和输出回收，不重新定义全部效果模型。
- 使用 `defer { kit.recycleOutput(output) }` 只适用于输出被同步消费的作用域。异步消费者必须完成复制或保留协议后再回收。
- SwiftUI 工程仍应把引擎放在独立 service/actor 或已有媒体层中，不把逐帧渲染放进 View body。

## 禁止照抄的示例

- 不使用文档中的旧模型名，如不带 `.next` 的 `ms_face240_v3.0.1.model`。
- 不把 `facecommon_v1.0.1.dat` 以 `NveDetectionModelType_face` 重复初始化；它对应 `faceCommon`。
- 美型对象必须赋给 `kit.shape`，不能把 beauty 变量误赋给 shape。
- 不沿用 demo 的 iOS 11 deployment target；以客户二进制的 `MinimumOSVersion` 为准。
- 不把 demo 页面中的授权调用位置作为最佳实践；授权由稳定的 process owner 管理并缓存成功状态，不在页面或逐帧路径重复调用。显式销毁后若还要重建，必须再次保证授权发生在新的 `shareInstance` 之前。
- 不把 demo 资源路径或 Bundle Identifier 写入客户代码。
