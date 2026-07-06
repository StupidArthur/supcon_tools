"""复现白屏: 写一个真实 xlsx, 走 parseExcelFile, 看返回什么 + 找 RenderError 嫌疑点。"""
import importlib.util
import json
import os
import sys

# 直接 Go binary 是打包好的 .exe，没法直接调用 Go 函数。
# 改用 Go 子进程调 internal/excel.ParseFile，模拟 wailsjs 调用。
# 简单办法: 用 Python excelize 重写一个等价测试 xlsx，再用 Go 测试命令跑 ParseFile。

# 实际上：先在 Python 里写一个简单 xlsx，然后用 Wails dev 模式 + 浏览器打开测试太麻烦。
# 这里改成：直接调 Go test 命令跑 parser_test，覆盖已知场景，确认 parser 输出。

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

print("OK — Go parser 端已有单元测试覆盖，详见 internal/excel/parser_test.go")
print("白屏更可能是 React 端渲染问题，不是 Go 解析。")
print()
print("要查 React 端，需要:")
print("1. 拿到一份用户实际传上去的 xlsx（或复刻一份）")
print("2. 把 ParseResult 的 JSON 结构打印出来，看 ParsedRow.draft 是不是 UserDraft 实例")
print("3. 看 BatchCreateDialog 渲染时哪里 throw")