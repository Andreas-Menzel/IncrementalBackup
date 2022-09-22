# IncrementalBackup - a rsync backup manager

## Python script to create incremental backups using rsync

IncrementalBackup is ...

## How can I use IncrementalBackup?

Execute `python3 IncrementalBackup.py --help` to get the following parameter list.

### Parameters

...

### Examples

The following examples should explain how the script works.

**Simple backup**

Create a backup of `/data` and save it to `/backup`.

```
python3 IncrementalBackup.py --src /data --dst /backup
```

You can also assign the source a unique id.

```
python3 IncrementalBackup.py --src MAIN#/data --dst /backup
```

**If you want to backup multiple source directories, you have to give each source a unique id.**

**Limit number of backups and exclude files**

Create a backup of `/data` and save it to `/backup`. Only keep the latest three backups and don't backup /data/no_backup/

```
python3 IncrementalBackup.py --src /data --dst /backup --keep 3 --exclude /data/no_backup
```

**Again: If you want to backup multiple source directories, you have to assign each --exclude to a id.**

**Backup with exclude**

## Used modules

For logging I use tizianerlenbergs [logHandler.py](https://github.com/tizianerlenberg/multiSSH/blob/6f48a3a5d0542fcb61682b9cb835b769b60e406b/logHandler.py) from his [multiSSH](https://github.com/tizianerlenberg/multiSSH) repository.
