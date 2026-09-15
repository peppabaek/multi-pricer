@echo off
chcp 65001 >nul
title GitHub 로그인
echo.
echo  ============================================================
echo    GitHub 로그인
echo  ============================================================
echo.
echo   아래 질문이 차례로 나옵니다. 화살표 키로 고르고 Enter:
echo.
echo     1) What account do you want to log into?
echo          -^> GitHub.com
echo.
echo     2) What is your preferred protocol for Git operations?
echo          -^> HTTPS
echo.
echo     3) Authenticate Git with your GitHub credentials?
echo          -^> Yes
echo.
echo     4) How would you like to authenticate GitHub CLI?
echo          -^> Login with a web browser
echo.
echo   그러면 XXXX-XXXX 형태의 코드가 나옵니다.
echo   Enter 를 누르면 브라우저가 열리니, 그 코드를 붙여넣고 승인하세요.
echo.
echo  ------------------------------------------------------------
echo.
pause
echo.

"%ProgramFiles%\GitHub CLI\gh.exe" auth login

echo.
echo  ------------------------------------------------------------
echo.
"%ProgramFiles%\GitHub CLI\gh.exe" auth status
echo.
echo   위에 "Logged in to github.com" 이 보이면 성공입니다.
echo   이 창을 닫고 Claude 에게 "로그인 완료" 라고 알려주세요.
echo.
pause
