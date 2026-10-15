# Gemini 4 Argon video by @NoHypeGuy

[Original post](https://x.com/NoHypeGuy/status/2110139470813225167)

- **Category:** Games & interactive
- **Built with:** Canvas
- **Author:** [@NoHypeGuy](https://x.com/NoHypeGuy)

## Prompt

```text
Build a single self-contained HTML file that is a fully functional fake operating system running in the browser. One file, no external dependencies, no CDN links, everything inline. It should open and immediately boot like a real computer.

Requirements-
1: a boot sequence with ASCII art logo, kernel messages scrolling line by line with realistic delays, ending in a login prompt. 
2: a login screen where the user types a username and password. Accept any input but respond with a witty error if the password is wrong, like "incorrect password, nice try." 
3: after login, launch a terminal-style shell with a command prompt. Support at least these commands: help, ls, cd, cat, mkdir, touch, rm, echo, date, whoami, uname, ping, history, clear, exit, and a secret command you invent that's hidden unless someone reads the source. 
4: implement a fake file system with directories like home, etc, var, tmp, and a few files with realistic content, like a README, a config file, and maybe a diary entry from the fictional OS creator. 
5: make cd actually change the working directory and update the prompt to show the current path. 
6: add a taskbar or status bar at the bottom showing time, username, and memory usage that ticks in real time. 
7: include a settings panel accessible from a menu where the user can change the wallpaper, font color, and terminal font. 
8: add a fun easter egg, like a snake game or a matrix rain effect triggered by a specific key combo. 
9: the whole thing should feel production quality, with smooth animations, a boot chime using the Web Audio API, and no console errors. 
10: at the end of the file, include a comment block listing every feature and command so people can see what you built.

Make it look and feel like a real retro-futuristic OS, think 1990s sci-fi meets modern polish. Do not ask me any questions. Just output the complete HTML file in one response.
```
