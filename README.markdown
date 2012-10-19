Xiki plugin for Sublime Text 2
====

To use: open the command pallete (`cmd+shift+p` or `ctrl+shift+p`) and use `Create Xiki Buffer`

Hotkeys:
----
  - `cmd+enter`: run or collapse the highlighted command/menu.
  - `cmd+shift+enter`: run the current command, and place the cursor after the output.
    - If used on a directory or file, will indent to the subdirectory level and create a command prompt (`$`)
    - If used on a command prompt, will maintain the current indentation and create a prompt (`$$` or `$`)

Useful SublimeXiki commands:
----

  - `/` or `~`: start a directory transversal tree. 
    - `~` starts at your home directory
    - You can also type a more complete path like `/path/to/dir` or `~/path`
  - `$`: run a command directly (does not invoke a shell)
  - `$$`: run a command using your default shell (allows pipes, redirection, logic, etc)

Useful Xiki commands:
----
  - `docs`
  - `mysql`
  - `mongo`
