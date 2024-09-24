# VSCode REH Launcher

Utility script used to launch VSCode REH (Remote Extension Host) server from [James' custom VSCode project](https://github.com/jamestut-vscode/vscode-patches).

## User Guide

1. Place the correct VSCode REH `.zip` file according to the platform in this repository's folder.
2. Optionally create the `config.json` file. See below section for more explanation.
3. Run the `launcher.py` script and enjoy!

You can check out the `run.pid` file to see the REH version in use.

### Config File

In this repo, create a file named `config.json` containing an object with the following keys:

- `host`: IP address or host name to listen on. Default is `127.0.0.1`.
- `port`: An integer containing the port number to listen on. Default is `3250`.
- `token`: A string containing the authentication token. Default is to not use an authentication token at all.
- `data-dir`: A string containing the location to server's data directory. Default is `server-data/data` in this repository's directory.
- `ext-dir`: A string containing the location to server's extensions directory. Default is `server-data/extensions` in this repository's directory.
- `pidfile`: Path to the file that contains information about the currently running instance. Default is `run.pid`.
- `logfile`: Path to the log file. Default is `server-data/reh-%pid.log`. `%pid` will be substituted by the PID of the launcher.
- `extra-args`: An array of string containing extra arguments to be passed to VSCode's REH.

**Example config:**

```json
{
    "host": "0.0.0.0",
    "port": 12345,
    "token": "SuperSecretAuthToken",
    "data_dir": "/home/user/vscode-data",
    "ext_dir": "/home/user/vscode-ext",
    "pidfile": "/var/run/vscodereh.pid",
    "logfile": "/var/log/vscode-reh-%pid.log",
    "extra_args": ["--grace-period", "3", "--telemetry-level", "all"]
}
```
## Behind the Scenes

When the `launcher.py` script is started, it will do the following:

1. Check the version number of the given `.zip` file against the one already extracted.
2. If the version number differs, stop the existing instance (if `run.pid` exists and is `flock`-ed), remove the old extracted files, and extract the new one from the given `.zip` file.
3. Starts VSCode REH as a daemon. The daemon will create the `run.pid` file and hold a lock on it.

## Prerequisites

**Supported systems:**

  - macOS arm64.
  - GNU/Linux arm64.
  - GNU/Linux x64.

**Additional requirements:**

- The `zip` and `uname` command.
- File system that supports `flock`.
