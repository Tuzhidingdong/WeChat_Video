from pathlib import Path
src = Path('Run_Literature_Micro_Visual.bat').read_bytes().split(b'\r\n')
head = [b'@echo off', b'chcp 65001 >nul', b'set RC=0', b'set STATE_FILE=C:\\temp\\state.json']
probe = head + src[47:50] + [b'exit /b 0']
Path('outputs/pre_flow_cleanup_retest_20261128/LOGS/echo_probe2.bat').write_bytes(b'\r\n'.join(probe) + b'\r\n')
