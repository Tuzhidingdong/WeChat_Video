from pathlib import Path
p = Path('outputs/pre_flow_cleanup_retest_20261128/LOGS/echo_probe2.bat')
data = p.read_bytes()
data = data.replace('echo [INFO] 状态文件：%STATE_FILE%'.encode('utf-8'),
                    b'echo [INFO] state_file: %STATE_FILE%')
Path('outputs/pre_flow_cleanup_retest_20261128/LOGS/echo_probe3.bat').write_bytes(data)
