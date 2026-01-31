@echo off
git status > debug_git.log 2>&1
git add . >> debug_git.log 2>&1
git commit -m "Debug commit" >> debug_git.log 2>&1
git push origin main >> debug_git.log 2>&1
