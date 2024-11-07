#!/usr/bin/env python3
import sys
import os
from os import path
import json
import fcntl
import argparse
import platform
import zipfile
import signal
from contextlib import contextmanager
import shutil
import subprocess
import select

platform_reh_name = None
config = None

def printe(*args, **kwargs):
    kwargs['file'] = sys.stderr
    print(*args, **kwargs)

class ConfigAccessor:
    _DEFAULT_BASE_DATADIR = "./server-data"
    _default_values = {
        "host": "127.0.0.1",
        "port": 3250,
        "token": None,
        "data_dir": path.join(_DEFAULT_BASE_DATADIR, "data"),
        "ext_dir": path.join(_DEFAULT_BASE_DATADIR, "extensions"),
        "extract_dir": ".",
        "pidfile": "run.pid",
        "logfile": path.join(_DEFAULT_BASE_DATADIR, "reh-%pid.log"),
        "extra_args": []
    }

    def __init__(self, configdata: dict):
        self._configdata = configdata
        # create the necessary directories
        for key_with_path in ["data_dir", "ext_dir", "extract_dir", "pidfile", "logfile"]:
            dirpath = path.dirname(getattr(self, key_with_path))
            if dirpath:
                os.makedirs(dirpath, exist_ok=True)

    def __getattribute__(self, name: str):
        if name in ConfigAccessor._default_values:
            return self._configdata.get(name,
                self._default_values[name])
        else:
            return super().__getattribute__(name)

def reh_launch_command():
    args = [
        path.join(get_reh_dir_path(), 'bin', 'code-server-oss'),
        "--host", config.host,
        "--port", config.port,
        "--server-data-dir", config.data_dir,
        "--extensions-dir", config.ext_dir
    ]
    if config.token:
        args.extend(["--connection-token", config.token])
    else:
        args.append("--without-connection-token")

    return [str(i) for i in args]

@contextmanager
def acquire_lock_file(blocking=True):
    nb_flag = fcntl.LOCK_NB if not blocking else 0
    with open(config.pidfile, 'a') as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | nb_flag)
            yield f
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def check_instance_running():
    '''
    Returns: PID, version
    '''
    try:
        with acquire_lock_file(blocking=False) as f:
            pass
        # acquire successful = previous instance is not running
        return None, None
    except BlockingIOError:
        pass

    # Failed w/ blocking error = running. Let's actually parse the PID file.
    with open(config.pidfile, 'r') as f:
        f.seek(0, 0)
        d = json.load(f)
    return d['pid'], d['version']

def extract_version_number_component(v):
    """
    Accepts version no. in the form of
    (supermajor).(major).(minor)-m(modrev)
    So far, supermajor is always 1.
    Returns: (supermajor, major, minor, modrev)
    """
    try:
        supermajor, major, minor = v.split(".")
        minor, modrev = minor.split("-")
        if not modrev.startswith('m'):
            raise ValueError()
        modrev = modrev[1:]
        return int(supermajor), int(major), int(minor), int(modrev)
    except ValueError:
        raise ValueError(f"Version number '{v}' not recognized")

def is_version_newer(now, other):
    assert any((now, other))
    if now is None:
        # nothing extracted yet: always newer
        return True
    if other is None:
        # no zip file: always older
        return False
    # both exists: do actual comparison
    return extract_version_number_component(other) > extract_version_number_component(now)

def get_version_number_from_existing():
    direxist, _ = dir_or_zip_exist()
    if not direxist:
        return None
    with open(path.join(get_reh_dir_path(), 'package.json'), 'r') as f:
        return get_version_number_from_pkg(f)

def get_version_number_from_zipfile():
    _, zipexist = dir_or_zip_exist()
    if not zipexist:
        return None
    with zipfile.ZipFile(f'{platform_reh_name}.zip', 'r') as zipobj:
        with zipobj.open(path.join(platform_reh_name, 'package.json')) as f:
            return get_version_number_from_pkg(f)

def get_version_number_from_pkg(f):
    pkginfo = json.load(f)
    return pkginfo['version']

def get_reh_dir_path(name=None):
    if name is None:
        name = platform_reh_name
    return path.join(config.extract_dir, name)

def dir_or_zip_exist(name=None):
    if name is None:
        name = platform_reh_name
    return path.isdir(get_reh_dir_path(name)), path.isfile(f'{name}.zip')

def populate_platform_reh_name_paths():
    global platform_reh_name

    try:
        PREFIX = 'vscode-reh-'
        plat_suffixes = {
            ('Darwin', 'arm64'): ['darwin-arm64'],
            ('Linux', 'x86_64'): ['linux-x64', 'linux-legacy-x64'],
            ('Linux', 'arm64'): ['linux-arm64', 'linux-legacy-arm64'],
        }.get((platform.system(), platform.machine()))

        if not plat_suffixes:
            raise RuntimeError(f"Platform {platform.system()} {platform.machine()} not supported.")

        # scan current directory for the presence of the .zip file and the folder
        available_names = []
        for suffix in plat_suffixes:
            plat_name_to_chk = f'{PREFIX}{suffix}'
            if any(dir_or_zip_exist(plat_name_to_chk)):
                available_names.append(plat_name_to_chk)

        if len(available_names) > 1:
            raise RuntimeError("Multiple VSCode REH with different platform suffix found.")
        elif not available_names:
            raise RuntimeError("No VSCode REH detected.")

        platform_reh_name = available_names[0]
    except Exception as ex:
        printe(str(ex))
        sys.exit(1)

def replace_extracted_version():
    # assume that the directory is unused and ready to be erased
    direxist, _ = dir_or_zip_exist()
    if direxist:
        print("Removing existing REH ...")
        shutil.rmtree(get_reh_dir_path())
    print("Extracting REH from zip file ...")
    subprocess.run(["unzip", "-q", f'{platform_reh_name}.zip', '-d', config.extract_dir])

def daemonize():
    sys.stdout.flush()
    sys.stderr.flush()

    pid = os.fork()
    if pid > 0:
        # exit the original parent process
        sys.exit(0)

    # decouple from parent's environment
    os.setsid()

    pid = os.fork()
    if pid > 0:
        # exit the second parent process
        sys.exit(0)

    # detach stdio
    null_si = os.open('/dev/null', os.O_RDONLY)
    os.dup2(null_si, sys.stdin.fileno())
    null_so = os.open('/dev/null', os.O_WRONLY)
    os.dup2(null_so, sys.stdout.fileno())
    null_se = os.open('/dev/null', os.O_WRONLY)
    os.dup2(null_se, sys.stderr.fileno())

def do_start_reh(foreground, reh_launch_args: list):
    if not foreground:
        daemonize()

    # open log file
    logfile = config.logfile.replace('%pid', str(os.getpid()))

    if foreground:
        print(f"Launcher's PID:", os.getpid())
        print(f"Log file:", logfile)

    with open(logfile, 'wb') as logf:
        # write PID file
        with acquire_lock_file() as f:
            f.seek(0, 0)
            f.truncate()
            json.dump({
                "pid": os.getpid(),
                "version": get_version_number_from_existing()
            }, f)
            f.flush()

            process = subprocess.Popen(reh_launch_args, text=False,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                preexec_fn=os.setpgrp)

            stdouterrfdmap = {
                process.stdout.fileno(): (sys.stdout.buffer.raw, process.stdout),
                process.stderr.fileno(): (sys.stderr.buffer.raw, process.stderr),
            }

            pfd = select.poll()
            # make the child's stdout/err for nonblocking and register them for poll
            for fd in stdouterrfdmap:
                os.set_blocking(fd, False)
                pfd.register(fd, select.POLLIN)

            # child's stdout/err read buffer
            rdbuff = bytearray(4096)
            rdbuffview = memoryview(rdbuff)

            try:
                while True:
                    for fd, _event in pfd.poll():
                        while True:
                            rdlen = stdouterrfdmap[fd][1].readinto1(rdbuff)
                            if not rdlen:
                                break
                            rddata = rdbuffview[:rdlen]
                            if foreground:
                                # to stdout/err
                                stdouterrfdmap[fd][0].write(rddata)
                            # to file
                            logf.write(rddata)
                            logf.flush()
            except KeyboardInterrupt:
                print("Stop requested.")
            finally:
                print("Stopping VSCode REH ...")
                os.killpg(os.getpgid(process.pid), signal.SIGINT)
                process.wait()

def termination_signal_handler(sig, frame):
    raise KeyboardInterrupt()

def main():
    global config

    DEFAULT_CONFIG_FILE = "config.json"

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", "-n", action="store_true",
        help="If specified, print the command that will be used to run "
        "VSCode REH.")
    ap.add_argument("--foreground", "-f", action="store_true",
        help="If specified, run in foreground instead of forking.")
    ap.add_argument("--config", "-c", default=DEFAULT_CONFIG_FILE,
        help=f"Specify the configuration file (default: {DEFAULT_CONFIG_FILE}).")
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, termination_signal_handler)

    # cwd to script's directory (repo's directory)
    script_dirname = path.dirname(sys.argv[0])
    if script_dirname:
        os.chdir(script_dirname)

    # check config file
    try:
        with open(args.config, 'r') as f:
            config_data = json.load(f)
    except FileNotFoundError:
        # all default settings
        config_data = {}
    except Exception as ex:
        printe('Error opening configuration file:', str(ex))
        sys.exit(1)

    config = ConfigAccessor(config_data)

    populate_platform_reh_name_paths()

    # check if instance is running
    try:
        running_pid, running_version = check_instance_running()
    except Exception as ex:
        printe("Error checking for existing instance:", str(ex))
        sys.exit(1)

    # do some reporting for dryrun
    if running_pid:
        print("Existing instance already running.")
        print("  PID    :", running_pid)
        print("  version:", running_version)

    zipfile_version = get_version_number_from_zipfile()
    if zipfile_version:
        print("Provided zip file version:", zipfile_version)
    existing_version = get_version_number_from_existing()
    if existing_version:
        print("existing REH version:", existing_version)

    reh_launch_args = reh_launch_command()
    if args.dry_run:
        print(" ".join(reh_launch_args))
        sys.exit(0)

    if running_pid:
        # zip file is newer: stop existing instance
        if is_version_newer(running_version, zipfile_version):
            print("Provided zip file have newer version. Stopping existing instance ...")
            os.kill(running_pid, signal.SIGTERM)
            # wait for the lock to be released
            with acquire_lock_file() as f:
                pass
        else:
            # do not (re)start the REH
            return
    # check again if the extracted version is the same as the zip file
    if is_version_newer(existing_version, zipfile_version):
        print("Provided zip file have newer version. Replacing existing ...")
        replace_extracted_version()
    do_start_reh(args.foreground, reh_launch_args)

if __name__ == "__main__":
    main()
