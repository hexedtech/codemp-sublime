[![codemp](https://code.mp/static/banner.png)](https://code.mp)

> `codemp` is a **collaborative** text editing solution to work remotely.

It seamlessly integrates in your editor providing remote cursors and instant text synchronization,
as well as a remote virtual workspace for you and your team.

# Codemp-Sublime
This is the reference [sublime](https://sublimetext.com) plugin for `codemp` maintained by [hexedtech](https://hexed.technology)


> [!WARNING]
> This package is still under active development, expect breakages and bugs.
> Make sure you keep backups of files in case they get corrupted during a session.

# Installation

## Package Control
The fastest and easiest way to install Codemp is via Package Control, the de-facto package manager for Sublime Text. 
Package Control not only installs your packages for you, it also ensures that they are kept up to date 
to make sure that you always have the benefit of the latest bug fixes and features for all of your installed packages.

> [!WARNING]
> This package requires Package Control v4, to install follow the steps below:


If you are new to Sublime Text and don't have Package Control installed yet, you'll have to do that first. 
<!-- More recent builds of Sublime Text have an option in the `Tools` menu named `Install Package Control...` that will install Package Control for you.
(won't show if package control is already installed!) -->
Unfortunately the installation of `Package Control v4` is not yet very streamlined, so for the time being you'll need to install
it manually:
- The first approach is to copy and paste the following line into your console (open with `ctrl+~`) press enter and then restart sublime:
```python
from urllib.request import urlretrieve;urlretrieve(url="https://github.com/wbond/package_control/releases/latest/download/Package.Control.sublime-package", filename=sublime.installed_packages_path() + '/Package Control.sublime-package')
```
- Alternatively, you can:
	1. download the latest [Package Control Release](https://github.com/wbond/package_control/releases/download/4.0.8/Package.Control.sublime-package)
	2. rename it to `Package Control.sublime-package` (get rid of the point between `Package` and `Control`)
	3. drag it into the `Installed Packages` folder.


* simply open the command palette again and select `Package Control: Install Package` and select `codemp`.

## Manual
Alternatively you can simply `git clone` this repository into your `Packages` folder:
You can access it via sublime through `Settings -> Browse Packages...`.

You will need to keep the package up to date yourself. As well as satisfying the dependency
(can be dont through package control.)

# Usage
## Overview
* All sublime windows share a single client session with a server.
* The workspaces are window specific, similarly to a `sublime-project`. So you can open `workspace-1` in one window and `workspace-2` in another, so long as both are in the same server and you have access to them.
* Explore the workspaces through the quick panel browser and join any buffer available to you.
* Start typing away.


## Quick start
 * first connect to server with `Codemp: Connect`
 * Explore available workspaces in the server with `Codemp: Browse Server`, it will open a quick panel browser.

 If you already know which workspace and buffer you want to join there are the commands:
 * `Codemp: Join Workspace`
 * `Codemp: Join Buffer`

## Commands
Interact with this plugin using the command palette. 

If an argument is shown between square brakets `[arg]` then the user will be prompted
if not present (either as simple text input or selecting from a list).

|	command label | arguments | description |
| --- | --- | --- |
| `Codemp: Connect` | `[host]` `[user]` `[password]` | to connect to a `codemp` server specified by `host` (defaults to the reference `http://code.mp` hexedtech server).

Once connected the following commands will become available:

|	command label | arguments | description |
| --- | --- | --- |
| `Codemp: Browse Server` | `None` | opens a quick panel browser to explore the workspaces of a server.
| `Codemp: Browse Workspace` | `None` | Explores the currently joined workspace.

You should be able to completely interact only through the quick panel browser, but if required below there are the single commands:

|	command label | arguments | description |
| --- | --- | --- |
|`Codemp: Disconnect Client` | `None` | disconnects the client from the server.
|`Codemp: Create Workspace` | `[workspace_id]` | create a workspace with the provided name.
|`Codemp: Delete Workspace` | `[workspace_id]` | delete an owned workspace from the server.
|`Codemp: Invite To Workspace` | `[workspace_id]` `[user_name]` | invite another registered codemp user to the specified workspace to begin collaborating.   
|`Codemp: Join Workspace` | `[workspace_id]` | join a workspace in the server, it can either be yours or one you were invited to. You can join multiple workspaces.

After joining a workspace the following commands will become available:

|	command label | arguments | description |
| --- | --- | --- |
|`Codemp: Leave Workspace` | `[workspace_id]` | leave the specified workspace, it will close all associated buffers.
| `Codemp: Create Buffer` | `[workspace_id]` `[buffer_id]` | creates the buffer `buffer_id` in the previously joined workspace `workspace_id`.
| `Codemp: Delete Buffer` | `[workspace_id]` `[buffer_id]` | deletes the buffer `buffer_id` in the previously joined workspace `workspace_id` that you own.
| `Codemp: Join Buffer` | `[workspace_id]` `[buffer_id]` | joins the specified buffer in the workspace and loads a file with its contents for you to interact with.

After Joining a buffer the following commands will become available:

|	command label | arguments | description |
| --- | --- | --- |
|`Codemp: Leave Buffer` | `[workspace_id]` `[buffer_id]` | detach from the specified buffer and closes the corresponding view (all changes will remain in the server).
| `Codemp: Sync` | `None` | forces an hard resync between this client and the server in case the buffer becomes corrupted. (handy when debugging and testing)

##
