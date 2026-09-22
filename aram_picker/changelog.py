"""Structured changelog data shown in the UI."""

CHANGELOG = [
    {
        "version": "1.7.1",
        "date": "2026-09-22",
        "items": [
            "修复更新日志页面文字看不清（版本信息改为红色显示）",
        ],
    },
    {
        "version": "1.7.0",
        "date": "2026-09-22",
        "items": [
            "新增「更新日志」页面，随时查看各版本更新内容",
            "版本升级后首次启动自动弹窗提示本次更新",
        ],
    },
    {
        "version": "1.6.0",
        "date": "2026-09-22",
        "items": [
            "换人结果通知：窗口可见时 InfoBar 横幅，托盘隐藏时系统通知",
            "换人成功 / 被队友抢走 / 验证超时均有提醒",
        ],
    },
    {
        "version": "1.5.1",
        "date": "2026-09-22",
        "items": [
            "修复双击换人后又换回去的问题（手动换人 500ms 防抖）",
        ],
    },
    {
        "version": "1.5.0",
        "date": "2026-09-22",
        "items": [
            "关闭窗口最小化到系统托盘常驻，双击图标恢复",
            "托盘菜单：显示主界面 / 退出",
            "自动接受对局开关状态记忆，重启不再重置",
        ],
    },
    {
        "version": "1.4.0",
        "date": "2026-09-22",
        "items": [
            "启动时强制弹出免责声明，确认后才开始服务",
            "选人页底部常驻红色免责声明",
        ],
    },
    {
        "version": "1.3.1",
        "date": "2026-09-21",
        "items": [
            "本命英雄优先级可自定义排序（双栏编辑弹窗，上移/下移/移除）",
        ],
    },
    {
        "version": "1.3.0",
        "date": "2026-09-21",
        "items": [
            "自动换不限次数：直到换到本命为止（被抢走/晚出现会重试）",
            "手动换人后本局自动换立即停止，不再覆盖玩家选择",
        ],
    },
    {
        "version": "1.2.2",
        "date": "2026-09-21",
        "items": [
            "头像 8 线程并发下载，启动即后台缓存全部英雄",
            "替补席与编辑弹窗图标放大到 32px",
        ],
    },
    {
        "version": "1.2.1",
        "date": "2026-09-21",
        "items": [
            "修复旧缓存缺少代号导致头像永远不下载的问题",
            "编辑弹窗自动补显下载完成的头像",
        ],
    },
    {
        "version": "1.2.0",
        "date": "2026-09-21",
        "items": [
            "替补席与编辑弹窗显示英雄头像（Data Dragon，本地缓存）",
        ],
    },
    {
        "version": "1.1.2",
        "date": "2026-09-20",
        "items": [
            "修复编辑本命弹窗深色主题下文字看不清的问题",
        ],
    },
    {
        "version": "1.1.1",
        "date": "2026-09-20",
        "items": [
            "修复未开客户端时点「编辑」无反应（缓存/Data Dragon 兜底加载）",
        ],
    },
    {
        "version": "1.1.0",
        "date": "2026-09-20",
        "items": [
            "自动换本命：按优先级盯守替补席，冷却中自动登记",
            "偏好设置持久化（config.json）",
        ],
    },
    {
        "version": "1.0.0",
        "date": "2026-09-20",
        "items": [
            "Fluent 风格界面重写（PyQt6 + qfluentwidgets，深色主题）",
            "大乱斗替补席一键换人、自动接受对局",
            "PyInstaller 打包脚本与一键运行 run.bat",
        ],
    },
]


def parse_version(version):
    """Turn '1.2.10' into a sortable tuple."""
    return tuple(int(part) for part in version.split("."))


def entries_since(last_seen):
    """Return changelog entries newer than last_seen (newest first).

    An unknown or empty last_seen version returns everything.
    """
    if not last_seen:
        return list(CHANGELOG)
    seen = parse_version(last_seen)
    for index, entry in enumerate(CHANGELOG):
        if parse_version(entry["version"]) <= seen:
            return CHANGELOG[:index]
    return list(CHANGELOG)
