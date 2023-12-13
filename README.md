# dusage

Show disk usage and quota on a cluster.
Supports BeeGFS and Lustre but is probably still too hard-coded for "our" clusters
and path locations.

![screenshot](img/screenshot.png)

Available options:

```console
$ dusage --help

Usage: dusage [OPTIONS]

Options:
  -u, --user TEXT     The username to check (default: *****).
  -p, --project TEXT  The allocation project.

  --no-colors         Disable colors.
  --help              Show this message and exit.
```
