@echo off
chcp 65001 >nul
set "RC=0"
set "STATE_FILE=C:\temp\state.json"
echo [INFO] 退出码 %RC% 仅供参考，成功与否以业务状态为准。
echo [INFO] 状态文件：%STATE_FILE%
echo [INFO] 报告目录：docs\reports\
