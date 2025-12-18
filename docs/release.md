# Releasing a new Nuclio-Jupyter version

> :bangbang: **Note:** The release can only be done by contributors with write access to the repository.

## Prerequisites

- Python 3.x installed
- `make`, `twine`, and `virtualenv` available
- Write access to the repository
- PyPI account and token

## Release Steps

1. Edit `nuclio/__init__.py` and bump version

2. Commit with message `Bump 0.x.y` and push to `upstream/development`

3. Checkout `master` branch:  
   `git checkout master`

4. Merge development into master and push:
```
git merge upstream/development
git push upstream master
```

5. Upload package to PyPI:
   1. Run `. ./venv/bin/activate && make upload`
   2. Enter your PyPI token when prompted

5. Verify package on PyPI

6. Create release on GitHub, use "Generate release notes" from a previously released version 
   1. **Release from Master!**

All done!
