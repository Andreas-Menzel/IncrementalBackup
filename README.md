# IncrementalBackup - a rsync backup manager

## Python script to create incremental backups using rsync

IncrementalBackup is a simple to use rsync wrapper for creating incremental
backups. It allows multiple source directories to be backuped at once and
provides multiple tests to ensure a safe backup procedure

IncrementalBackup will check the existance of the source- and destination
directories, as well as check-files that ensure that a backup from / to the
specified directory is intended. This is especially useful if the backup is done
to an external hard drive. If it is not connected, no backup will be done and
rsync will not be executed.

If the maximum number of backups at the destination location is reached
(if specified; see `--keep`), the oldest backup will be recycled to reduce the
runtime.

## How can I use IncrementalBackup?

Execute `python3 IncrementalBackup.py --help` to get the following help 
message / parameter list.

### Parameters

```
usage: IncrementalBackup --src ID#PATH [ID#PATH ...] --dst DST [-h] [--version] [--keep KEEP] [--exclude ID#PATH [ID#PATH ...]] [--dst_fqdn DST_FQDN]

Create incremental backups.

required arguments:
  --src ID#PATH [ID#PATH ...]
                        Data directories + identifiers.
  --dst DST             Backup directory.

optional arguments:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --keep KEEP           Number of backups to keep. 0 = no limit. Default is 0.
  --exclude ID#PATH [ID#PATH ...]
                        Paths to exclude from the backup.
  --dst_fqdn DST_FQDN   Add fully qualified domain name to the backup path. Default is True.
```

### Explanation

#### Specify data- and backup-directory (required)

Use `--src` and `--dst` to specify the paths to the data *(source)* and
backup *(destination)* directories.

You can also specify more than one source directory. In this case a unique id
must be assigned to each source in the format `<id>#<path>`:

```
python3 IncrementalBackup.py --scr DATA#/data WWW#/var/www --dst /backup
```

You can also assign an id to the source if you are only using one source
directoy. This is not required, however.

#### (Don't) save backup to FQDN subfolder

You may have noticed, that the backup will be saved to a subfolder of `--dst` 
named by the fully-qualified-domain-name of the computer. This feature is
enabled by default and was implemented so one can easily see where the backups
come from.

You can disable this feature by specifying `--dst_fqdn`:

```
python3 IncrementalBackup.py --src /data --dst /backup --dst_fqdn False
```

#### Exclude files and direcories from the backup

Use `--exclude` to exclude one or multiple files and / or directories from the
backup:

```
python3 IncrementalBackup.py --src /data --dst /backup --exclude /data/exclude_me/ /data/me_too.md
```

You can assign the id of the source to the exclude paths. **This is required
if the source was assigned an id.** Again: use the format `<id>#<PATH>`:

```
python3 IncrementalBackup.py --src DATA#/data WWW#/var/www --dst /backup --exclude DATA#/data/exclude_me/ WWW#/var/www/me_too.md
```

#### Limit number of backups

You can also limit the number of backups saved at the destination by specifying
`--keep`:

```
python3 IncrementalBackup.py --src /data --dst /backup --keep 5
```

This will delete all but the latest 5 backups. The fifth-latest backup will be
recycled; the execution time can be drastically reduced.



## Used modules

For logging I use tizianerlenbergs [logHandler.py](https://github.com/tizianerlenberg/multiSSH/blob/6f48a3a5d0542fcb61682b9cb835b769b60e406b/logHandler.py) from his [multiSSH](https://github.com/tizianerlenberg/multiSSH) repository.
