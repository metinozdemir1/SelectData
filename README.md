# SelectData

Picks cases and variables from a large SPSS (`.sav`) file and saves the subset as
`.sav` (variable labels, value labels and missing values are kept), `.csv`, `.xlsx` or `.dta`.
It reads the file in chunks and only loads the columns it needs, so very large files are fine.

## Window mode

Double-click `SelectData.exe`, or run `python selectdata.py` with no arguments.

1. **Open .sav file…**
2. Tick the variables to keep (use the search box; Ctrl/Shift-click for several). If you select none, all variables are kept.
3. Fill in any filters: country, age range, gender, number of cases.
4. Click **Select and save…**

The country, age and gender variables are detected automatically. If one is wrong, type the
correct name. The **values** button shows the codes and counts for that variable.

## Command mode

```
SelectData info data.sav                     list variables
SelectData info data.sav --values cntry      show codes and counts for one variable

SelectData data.sav --vars idno,cntry,agea,gndr,q1-q10 --country SE,NO --age 18-65 --gender 2 --n 1000 --out subset.sav
```

| Option | Meaning | Examples |
|---|---|---|
| `--vars`, `-v` | variables to keep (default: all). `a-b` or `a TO b` = range in file order | `id,q1-q10` |
| `--country`, `-c` | country codes **or** value labels | `SE,NO` · `752` · `Sweden` |
| `--age`, `-a` | range or list | `18-65` · `30-` · `-29` · `20,30` |
| `--gender`, `-g` | codes or labels | `2` · `Female` |
| `--where`, `-w` | any other variable (can be repeated) | `"edu=3,4"` · `"income=1-5"` |
| `--n`, `-n` | number of cases to keep (random sample) | `1000` |
| `--first` | take the first N cases instead of a random sample | |
| `--seed` | random seed, so you get the same sample again (default 12345) | `2026` |
| `--out`, `-o` | output file; the extension sets the format (default `<input>_subset.sav`) | `out.csv` |
| `--country-var` etc. | name of the variable to use if it isn't detected automatically | `--age-var alder` |

You can combine any of the filters. A case is kept only if it matches all of them.

## Building the standalone program (one time)

You need Python 3.10+ on the machine you build on. The finished program runs without Python.

- **Windows:** install Python from python.org (tick "Add to PATH"), then double-click `build_windows.bat` → `dist\SelectData.exe`
- **Mac / Linux:** run `./build_mac_linux.sh` → `dist/SelectData`

Build it on the same kind of system it will run on. A Windows `.exe` has to be built on Windows.

You can also skip the build and run it straight from Python:
`pip install -r requirements.txt` then `python selectdata.py ...`

## Notes for CY09_MS_STU_PUF.sav (tested 3 Nov 2026)

- Detected automatically: country = `CNT` (3-letter codes, e.g. SWE, or names such as Sweden), age = `AGE`, gender = `ST004D01T` (1 = Female, 2 = Male).
- `ST004D01T` has no gender data (all 99) for ARG, AUS, BEL, CAN, CHL, COL, DEU, DNK, ESP, IRL, ISL, NLD, NZL, URY.
  For those countries use `--gender-var MALE` (0 = Female/Other, 1 = Male), which is filled in for all of them.
- `AGE` is 97 (not applicable) for all students in NOR and LUX, so an age filter removes those countries.
- The program warns you when a requested code doesn't exist in the file, or when it does exist but every case is removed by another filter.

Example:

    python3 selectdata.py ../CY09_MS_STU_PUF.sav --vars CNT,CNTSCHID,CNTSTUID,MALE,AGE,W_FSTUWT --country SWE,NOR,DNK,FIN,ISL --gender-var MALE --gender 0 --n 5000 --out ../Output/nordic_girls_5000.sav

## Automatic builds on GitHub (Windows + Mac)

`build.yml` makes GitHub build and test the program for Windows, Mac (Apple chip) and Mac (Intel) for free.
It must be placed in the repository as `.github/workflows/build.yml`. Publish a Release (e.g. `v1.0`) to get
the three zip files attached to it: SelectData-Windows.zip, SelectData-Mac-AppleChip.zip, SelectData-Mac-Intel.zip.
