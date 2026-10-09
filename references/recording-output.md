# 录制输出接入规范

## 目录

- [适用范围](#适用范围)
- [接入前先明确产品契约](#接入前先明确产品契约)
- [实施要求](#实施要求)
- [推荐帧链](#推荐帧链)
- [开始与停止](#开始与停止)
- [已验证的默认录制 UI](#已验证的默认录制-ui)
- [录制验收](#录制验收)

## 适用范围

当客户工程需要把 NVE 实时渲染结果写入视频文件，或需要修复录制时间戳、前摄成片镜像、停止顺序、保存结果和录制入口 UI 时，执行本规范。录制是渲染结果的输出消费者，不是 NVE 效果模块。

优先复用客户已有录制器、音频链和状态机。不要为了接入 NVE 引入第二套完整相机、页面或媒体架构，也不要在没有跨项目证据时提供通用 writer 模板。

## 接入前先明确产品契约

1. 录制是仅视频还是音视频；没有音轨必须显式声明为 video-only，不能因为没有音频格式而永远无法开始。
2. 前摄成片是“与镜像预览一致”还是“真实非镜像”。两者都合理，但必须由产品规则决定。
3. 录制期间是否允许切换摄像头、分辨率或像素格式。没有既有规则时默认禁用；需要支持时按分段或显式格式迁移处理。
4. 保存成功的定义：writer 异步完成、输出文件可读且非空；写入系统相册失败时是否保留本地文件并提示恢复路径。

## 实施要求

录制主流程保持：

1. 相机输出视频 sample buffer；需要音轨时，麦克风独立输出音频 sample buffer。
2. 视频帧先交给 NVE 渲染；渲染 output 同时用于预览和录制。
3. 按 [帧方向与镜像契约](frame-geometry-contract.md) 先确定唯一 mirror owner；默认链在 NVE 输入端生成镜像像素，已取证兼容链在 capture connection 生成镜像像素。录制要求非镜像时由独立 recording-owned frame 在消费者边界做一次反镜像。
4. writer 获得本次录制所需的格式后准备 input，在第一帧实际接受的视频到达时 `startWriting` / `startSession`。
5. 视频以及可选音频分别追加到对应 writer input，结束后异步完成文件写入。
6. 在异步消费者持有 output payload 后回收 NVE output，避免把已经回收的 buffer 交给 writer。
7. writer 完成并确认文件可读、非空后，再保存到系统相册或交给其他目标消费者。

### 时间戳

`CMTime.value` 必须结合其 `timescale` 才有意义。不能只对 `value` 做整数缩放后再指定新的 timescale，也不能从未声明时基的时间字段推断录制时间线。

录制视频应使用源 sample buffer 的 presentation timestamp，或使用客户录制器已经验证的显式换算。提交给 writer 的 PTS 必须严格单调；writer 背压导致丢帧时不能为了补帧而猜测或重写时间线。`renderTimestamp` 未知时基时保持 SDK 默认，不能替代录制 PTS。

### 停止顺序

停止接收新帧并排空录制队列后，先对所有 writer input 调用 `markAsFinished`，再调用 `finishWriting`。不能在 `finishWriting` 之后才标记 input 完成。

### 异常分支所有权

若使用 `CVPixelBufferRetain`、复制或 lease 把 NVE output 交给异步 writer，成功、writer 失败、未 ready、提前返回和停止中的每条路径都必须释放对应所有权。NVE `renderOutput` 仍需恰好回收一次。

### 音频契约

音视频录制应等待所需的视频和音频 format description 齐备后初始化对应 inputs。客户工程如果只录视频，应建立 video-only writer，不能把音频格式设为隐含启动条件。

### 镜像边界

若客户产品要求前摄成片与镜像预览一致，选定的 NVE 或 capture owner 只镜像一次，preview/writer 都不再 transform。若产品要求成片非镜像，preview 和 writer 必须各自取得 owned frame，writer 对其副本执行一次明确的反镜像；不得修改共享 preview buffer，也不得同时启用 capture、NVE 或 preview 中两个 mirror owner。

方向判断必须使用该帧采集时的 camera position 快照，不能在异步写入时读取可能已经变化的全局相机状态。至少用文字或其他非对称画面验证前后摄成片。

## 推荐帧链

```text
capture sample + source PTS + camera snapshot
  → NVE render
  → 为预览建立独立所有权
  → 为录制建立独立所有权并提交有序 writer 队列
  → NVE output 恰好 recycle 一次
```

预览可以使用 capacity-one mailbox 丢弃旧帧；录制不能复用这个 mailbox。录制只沿用客户录制器明确的背压和丢帧策略。

## 开始与停止

开始录制：

1. 确认授权、模型、NVE 实例、相机和录制器 ready。
2. 固定本段录制的视频尺寸、像素格式、方向和镜像规则。
3. 使用第一帧实际接受的视频 PTS 开始 writer session。
4. 只有 writer 真正接受录制后，UI 才进入 recording。

停止录制：

1. 状态进入 stopping，阻止新录制帧入队。
2. 排空已经接受的录制任务。
3. 对全部 writer input 执行 `markAsFinished`。
4. 调用 `finishWriting` 并等待完成回调。
5. 验证文件可读且非空，再进入保存状态。
6. 相册保存失败时按产品规则保留本地文件并展示可恢复错误。
7. 状态回到 idle 后才允许下一次录制。

必须连续录制至少两次，防止第二次 writer/session 状态未重置。

## 已验证的默认录制 UI

只有用户没有指定设计且工程没有可复用录制 UI 时，才执行 [默认效果 UI](default-ui.md) 的共享底栏、录制入口、摄像头切换和完成提示契约。本文件只补充录制状态机要求：idle/recording 使用可区分的录制/停止符号，starting、stopping 和 saving 期间避免重复点击。

## 录制验收

- 前后摄各录制一次，并连续完成第二次录制。
- 输出文件可读、非空，可正常播放，帧顺序和时长合理。
- 视频 PTS 严格单调；有音频时验证 A/V 同步，无音频时确认产品明确接受 video-only。
- 使用文字或非对称物体确认前摄成片符合产品镜像规则，后摄方向正常。
- 录制时切换效果、展开/收起面板不会停止录制或破坏文件。
- 录制完成提示在规定时间自动消失。
- 录制期间摄像头切换符合禁用、分段或格式迁移的既定规则。
- 退后台、权限失败、writer 失败和保存失败不会留下无法再次开始的中间状态。
