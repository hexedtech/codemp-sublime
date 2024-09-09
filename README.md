[![codemp](https://code.mp/static/banner.png)](https://code.mp)

> `codemp` is a **collaborative** text editing solution to work remotely.

It seamlessly integrates in your editor providing remote cursors and instant text synchronization,
as well as a remote virtual workspace for you and your team.

# Codemp-Sublime
This is the reference [sublime](https://sublimetext.com) plugin for `codemp` maintained by [hexedtech](https://hexed.technology)

> [!IMPORTANT]
> The plugin is in active development. Expect frequent changes.

# Installation
> [!IMPORTANT]
> Currently the python bindings are only available for macOS, this will change shortly.

## Package Control
The fastest and easiest way to install Codemp is via Package Control, the de-facto package manager for Sublime Text. 
Package Control not only installs your packages for you, it also ensures that they are kept up to date 
to make sure that you always have the benefit of the latest bug fixes and features for all of your installed packages.

If you are new to Sublime Text and don't have Package Control installed yet, you'll have to do that first. 
More recent builds of Sublime Text have an option in the `Tools` menu named `Install Package Control...` that will install Package Control for you.
(won't show if package control is already installed!)

Currently this package is not on the sublime package repository.
But it can still be installed by package control.
* Open the command palette in Sublime (`Shift+Ctrl+P` on Windows/Linux or `Shift+⌘+P` on MacOS)
* select the `Package Control: Add Repository` command and paste `https://github.com/hexedtech/codemp-sublime.git` into the quick panel
* open the command palette again and select `Package Control: Install Package` and select `codemp-sublime`.

## Manual
Alternatively you can simply `git clone` this repository into your `Packages` folder:
You can access it via sublime through `Settings -> Browse Packages...`.

You will need to keep the package up to date yourself.

# Usage
## Overview
* All sublime windows share a single client session with a server.
* The workspaces are window specific, similarly to a `sublime-project`. So you can open `workspace-1` in one window and `workspace-2` in another, so long as both are in the same server and you have access to them.
* Joining a workspace will materialize a virtual file system mimicking the remote one as if it were a project folder.


## Quick start
 * first connect to server with `Codemp: Connect`
 * then join a workspace with `Codemp: Join Workspace`
 * attach directly to a buffer with `Codemp: Join Buffer` and start typing away!

all commands will provide a list of available ids to chose from

## Commands
Interact with this plugin using the command palette. 
In future versions side bar interaction will be attempted.

If an argument is shown between square brakets `[arg]` then the user will be prompted
if not present (either as simple text input or selecting from a list).

|	command label | arguments | description |
| --- | --- | --- |
| `Codemp: Connect` | `[host]` `[user]` `[password]` | to connect to a `codemp` server specified by `host` (defaults to the reference `http://code.mp` hexedtech server).

Once connected the following commands will become available:

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

##
