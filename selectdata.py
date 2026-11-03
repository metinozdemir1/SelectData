#!/usr/bin/env python3
"""
SelectData - pick cases and variables from a large SPSS (.sav) file.

Two ways to use it:

  1. GUI:  run without arguments (or double-click)      ->  selectdata
  2. Command line:

     selectdata info  data.sav                       list all variables
     selectdata info  data.sav --values cntry        show codes/counts for a variable
     selectdata data.sav --vars cntry,agea,gndr,q1-q10 --country SE,NO
                         --age 18-65 --gender 2 --n 1000 --out subset.sav

Case filters (all optional, combined with AND):
  --country  codes or value labels, comma-separated   e.g. SE,NO   or 752,578  or Sweden
  --age      range or list                            e.g. 18-65   30-   -29   20,30,40
  --gender   codes or value labels                    e.g. 2       or Female
  --where    any other variable: VAR=VALUES           e.g. --where "edu=3,4" (repeatable)
  --n        number of cases to keep (random sample unless --first is given)
  --seed     random seed so the sample can be reproduced (default 12345)

The country/age/gender variables are detected automatically from common names
(cntry, country, age, agea, gndr, gender, sex ...). Override with
--country-var, --age-var, --gender-var.

Output format follows the file extension: .sav (keeps labels), .csv, .xlsx, .dta
"""

import argparse
import os
import re
import sys

import pandas as pd
import pyreadstat

__version__ = "1.0"

COMMON_NAMES = {
    "country": ["cntry", "country", "countrycode", "country_code", "ccode", "cnt", "land", "nation"],
    "age": ["age", "agea", "age_r", "ageyears", "alder", "ålder", "yrbrn_age"],
    "gender": ["gndr", "gender", "sex", "kon", "kön", "female"],
}
LABEL_WORDS = {
    "country": r"\b(country|land)\b",
    "age": r"\b(age|ålder)\b",
    "gender": r"\b(gender|sex|kön)\b",
}
CHUNK_ROWS = 200_000
CELLS_PER_CHUNK = 20_000_000  # rows x variables read at once (keeps memory low)


# --------------------------------------------------------------------------- #
# Reading metadata
# --------------------------------------------------------------------------- #
def read_meta(path):
    """Read only the dictionary (variables, labels) - fast even for huge files."""
    _, meta = pyreadstat.read_sav(path, metadataonly=True, user_missing=True)
    return meta


def detect_var(meta, kind):
    lower = {n.lower(): n for n in meta.column_names}
    for cand in COMMON_NAMES[kind]:
        if cand in lower:
            return lower[cand]
    # fall back to the variable labels, e.g. ST004D01T "Students' gender ..."
    for name, label in zip(meta.column_names, meta.column_labels):
        if label and re.search(LABEL_WORDS[kind], label, flags=re.I):
            return name
    return None


def expand_vars(spec, meta):
    """'a,b,q1-q5,x TO y' -> list of variable names (ranges follow file order)."""
    names = meta.column_names
    lower = {n.lower(): n for n in names}

    def find(n):
        n = n.strip()
        if n.lower() not in lower:
            raise ValueError(f"Variable not found: {n}")
        return lower[n.lower()]

    out = []
    spec = re.sub(r"\s+to\s+", "-", spec, flags=re.I)
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        if part == "*" or part.lower() == "all":
            out.extend(names)
        elif "-" in part:
            a, b = part.split("-", 1)
            i, j = names.index(find(a)), names.index(find(b))
            if i > j:
                i, j = j, i
            out.extend(names[i:j + 1])
        else:
            out.append(find(part))
    seen = set()
    return [v for v in out if not (v in seen or seen.add(v))]


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def _norm(x):
    """Normalise a value for comparison: 2, 2.0 and '2' are all '2'."""
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return str(x).strip().lower()


def make_value_filter(var, text, meta):
    """Match codes OR value labels, e.g. 'SE,NO' or '752' or 'Sweden'."""
    wanted = {_norm(t) for t in text.split(",") if t.strip()}
    labels = meta.variable_value_labels.get(var, {})
    for code, lab in labels.items():           # allow label names
        if _norm(lab) in wanted:
            wanted.add(_norm(code))

    def f(col):
        return col.map(_norm).isin(wanted)
    return f


def make_range_filter(var, text):
    """'18-65', '30-', '-29', '20,30,40' or a single number."""
    text = text.replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)?[-:](\d+(?:\.\d+)?)?", text) if "," not in text else None
    if m and (m.group(1) or m.group(2)):
        lo = float(m.group(1)) if m.group(1) else None
        hi = float(m.group(2)) if m.group(2) else None

        def f(col):
            c = pd.to_numeric(col, errors="coerce")
            ok = c.notna()
            if lo is not None:
                ok &= c >= lo
            if hi is not None:
                ok &= c <= hi
            return ok
        return f
    vals = {float(v) for v in text.split(",") if v}
    return lambda col: pd.to_numeric(col, errors="coerce").isin(vals)


def build_filters(opts, meta):
    """Return list of (variable, function, description, kind, value)."""
    filters = []
    for kind in ("country", "age", "gender"):
        value = opts.get(kind)
        if not value:
            continue
        var = opts.get(kind + "_var") or detect_var(meta, kind)
        if not var:
            raise ValueError(f"Could not find a {kind} variable automatically. "
                             f"Please specify it with --{kind}-var.")
        var = expand_vars(var, meta)[0]
        fn = make_range_filter(var, value) if kind == "age" else make_value_filter(var, value, meta)
        filters.append((var, fn, f"{var} = {value}", kind, value))
    for cond in opts.get("where") or []:
        if "=" not in cond:
            raise ValueError(f"--where must look like VAR=VALUES, got: {cond}")
        var, value = cond.split("=", 1)
        var = expand_vars(var, meta)[0]
        is_range = re.search(r"\d\s*[-:]\s*\d|^[-:]|[-:]$", value.strip())
        fn = make_range_filter(var, value) if is_range else make_value_filter(var, value, meta)
        filters.append((var, fn, f"{var} = {value}", "where", value))
    return filters


# --------------------------------------------------------------------------- #
# Main work
# --------------------------------------------------------------------------- #
def select(path, out, variables=None, country=None, age=None, gender=None, where=None,
           country_var=None, age_var=None, gender_var=None,
           n=None, first=False, seed=12345, log=print):
    meta = read_meta(path)
    log(f"File: {os.path.basename(path)}  ({meta.number_rows or '?'} cases, "
        f"{meta.number_columns} variables)")

    keep = expand_vars(variables, meta) if variables else list(meta.column_names)
    filters = build_filters(dict(country=country, age=age, gender=gender, where=where,
                                 country_var=country_var, age_var=age_var,
                                 gender_var=gender_var), meta)
    for _, _, d, _, _ in filters:
        log(f"  filter: {d}")

    filter_vars = list(dict.fromkeys(f[0] for f in filters))

    # Pass 1: read only the filter variables to find the matching cases (fast, low memory)
    rows, seen = [], {}
    if filters:
        offset = 0
        for chunk, _ in pyreadstat.read_file_in_chunks(pyreadstat.read_sav, path, chunksize=CHUNK_ROWS,
                                                       usecols=filter_vars, user_missing=True):
            mask = pd.Series(True, index=chunk.index)
            for var, fn, *_ in filters:
                mask &= fn(chunk[var])
                seen.setdefault(var, set()).update(chunk[var].dropna().unique().tolist())
            rows.extend((offset + chunk.index[mask.values]).tolist())
            offset += len(chunk)
            log(f"  checked {offset:,} cases ...", end="\r")
            if first and n and len(rows) >= n:
                break
        log("")
        matched = len(rows)
        log(f"  {matched:,} cases match the filters")
    else:
        matched = meta.number_rows or 0
        rows = None
        log(f"  no case filters: all {matched:,} cases")

    # Reduce to the requested number of cases
    if n and matched > n:
        import numpy as np
        if rows is None:
            rows = list(range(matched))
        if first:
            rows = rows[:n]
        else:
            rng = np.random.default_rng(seed)
            rows = sorted(rng.choice(rows, size=n, replace=False).tolist())
        log(f"  keeping {'first' if first else 'random'} {n:,} cases"
            + ("" if first else f" (seed {seed})"))
    elif n:
        log(f"  note: only {matched:,} cases available, fewer than the {n:,} requested")

    # Pass 2: read the chosen variables in small chunks and keep only the chosen cases
    read_cols = [c for c in meta.column_names if c in set(keep) | set(filter_vars)]
    chunk_rows = max(2000, min(CHUNK_ROWS, CELLS_PER_CHUNK // max(1, len(read_cols))))
    total = meta.number_rows or 0
    if rows is None:                       # no filters and no sampling: everything
        rows = range(total)
    parts, i, done = [], 0, 0
    while i < len(rows):
        # one block = the chosen cases that lie within chunk_rows of each other
        start = rows[i]
        j = i
        while j < len(rows) and rows[j] < start + chunk_rows:
            j += 1
        block = rows[i:j]
        chunk, _ = pyreadstat.read_sav(path, usecols=read_cols, user_missing=True,
                                       row_offset=start, row_limit=block[-1] - start + 1)
        local = [r - start for r in block]
        parts.append(chunk.iloc[local] if len(local) < len(chunk) else chunk)
        done += len(block); i = j
        log(f"  reading data: {done:,} of {len(rows):,} cases ...", end="\r")
    log("")
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=read_cols)
    # warn about requested codes that produced no cases (e.g. a country without age data)
    for var, _, _, kind, value in filters:
        if kind in ("country", "gender", "where") and not re.search(r"\d\s*[-:]\s*\d", value):
            asked = [t.strip() for t in value.split(",") if t.strip()]
            in_file = pd.Series(list(seen.get(var, [])), dtype=object)
            absent = [t for t in asked if not make_value_filter(var, t, meta)(in_file).any()]
            dropped = [t for t in asked if t not in absent
                       and not make_value_filter(var, t, meta)(df[var]).any()]
            if absent:
                log(f"  WARNING: {', '.join(absent)} does not occur in {var} "
                    f"(run 'info FILE --values {var}' to see valid codes)")
            if dropped:
                log(f"  WARNING: {var} = {', '.join(dropped)} exists, but no cases are left after "
                    f"the other filters (often because that variable is missing there)")
    if df.empty:
        raise ValueError("No cases match the selection - nothing was saved.")
    df = df[keep]
    df = df.reset_index(drop=True)
    write(df, out, meta)
    log(f"Saved {len(df):,} cases x {df.shape[1]} variables -> {out}")
    return df


def write(df, out, meta):
    ext = os.path.splitext(out)[1].lower()
    cols = list(df.columns)
    if ext == ".sav":
        sub = lambda d: {k: v for k, v in (d or {}).items() if k in cols}
        labels = dict(zip(meta.column_names, meta.column_labels))
        pyreadstat.write_sav(
            df, out,
            column_labels=[labels.get(c) for c in cols],
            variable_value_labels=sub(meta.variable_value_labels),
            missing_ranges=sub(meta.missing_ranges),
            variable_measure=sub(meta.variable_measure),
            variable_display_width=sub(meta.variable_display_width),
            variable_format=sub(meta.original_variable_types),
        )
    elif ext == ".dta":
        pyreadstat.write_dta(df, out, variable_value_labels={
            k: v for k, v in meta.variable_value_labels.items() if k in cols})
    else:
        # show 3.0 as 3 in text/Excel output
        df = df.copy()
        for c in df.select_dtypes("float").columns:
            s = df[c].dropna()
            if len(s) and (s % 1 == 0).all():
                df[c] = df[c].astype("Int64")
    if ext in (".sav", ".dta"):
        pass
    elif ext in (".xlsx", ".xls"):
        df.to_excel(out, index=False)
    elif ext == ".tsv" or ext == ".txt":
        df.to_csv(out, index=False, sep="\t")
    else:
        df.to_csv(out, index=False)


def info(path, values=None):
    meta = read_meta(path)
    if values:
        var = expand_vars(values, meta)[0]
        df, _ = pyreadstat.read_sav(path, usecols=[var], user_missing=True)
        labs = meta.variable_value_labels.get(var, {})
        counts = df[var].value_counts(dropna=False).sort_index()
        print(f"{var}: {dict(zip(meta.column_names, meta.column_labels)).get(var) or ''}")
        for code, cnt in counts.items():
            print(f"  {str(code):>10}  {cnt:>9,}  {labs.get(code, '')}")
        return
    print(f"{meta.number_rows or '?'} cases, {meta.number_columns} variables\n")
    for name, lab in zip(meta.column_names, meta.column_labels):
        print(f"  {name:<20} {lab or ''}")
    for kind in COMMON_NAMES:
        v = detect_var(meta, kind)
        print(f"\nDetected {kind} variable: {v or '(none - use --' + kind + '-var)'}", end="")
    print()


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #
def cli(argv):
    if argv and argv[0] == "info":
        p = argparse.ArgumentParser(prog="selectdata info")
        p.add_argument("file")
        p.add_argument("--values", metavar="VAR", help="show codes and counts for VAR")
        a = p.parse_args(argv[1:])
        info(a.file, a.values)
        return

    p = argparse.ArgumentParser(prog="selectdata",
                                description="Select cases and variables from an SPSS .sav file.",
                                epilog="Run 'selectdata info FILE' to list variables. "
                                       "Run without arguments to open the window.")
    p.add_argument("file", help="input .sav file")
    p.add_argument("--vars", "-v", help="variables to keep, e.g. id,cntry,q1-q10 (default: all)")
    p.add_argument("--country", "-c", help="country codes/labels, e.g. SE,NO")
    p.add_argument("--age", "-a", help="age range, e.g. 18-65")
    p.add_argument("--gender", "-g", help="gender code(s)/label(s), e.g. 2")
    p.add_argument("--where", "-w", action="append", help='other filter, e.g. "edu=3,4"')
    p.add_argument("--country-var"); p.add_argument("--age-var"); p.add_argument("--gender-var")
    p.add_argument("--n", "-n", type=int, help="number of cases to keep (random)")
    p.add_argument("--first", action="store_true", help="take the first N instead of random")
    p.add_argument("--seed", type=int, default=12345)
    p.add_argument("--out", "-o", help="output file (.sav .csv .xlsx .dta). "
                                       "Default: <input>_subset.sav")
    p.add_argument("--version", action="version", version=__version__)
    a = p.parse_args(argv)
    out = a.out or os.path.splitext(a.file)[0] + "_subset.sav"
    printer = lambda *x, **k: print(*x, **k, flush=True)
    select(a.file, out, a.vars, a.country, a.age, a.gender, a.where,
           a.country_var, a.age_var, a.gender_var, a.n, a.first, a.seed, log=printer)


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
def gui():
    import queue
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"SelectData {__version__}")
    root.geometry("820x640")
    st = {"meta": None, "path": None}

    def labelled(parent, text, row, width=30):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=2)
        var = tk.StringVar()
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="we", pady=2)
        return var

    # --- file row
    top = ttk.Frame(root, padding=8); top.pack(fill="x")
    file_var = tk.StringVar(value="No file opened")
    ttk.Button(top, text="Open .sav file…", command=lambda: open_file()).pack(side="left")
    ttk.Label(top, textvariable=file_var).pack(side="left", padx=8)

    body = ttk.Frame(root, padding=8); body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1); body.rowconfigure(0, weight=1)

    # --- variable list
    left = ttk.LabelFrame(body, text="Variables to keep (none selected = all)", padding=6)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    search = tk.StringVar()
    ttk.Entry(left, textvariable=search).pack(fill="x")
    btns = ttk.Frame(left); btns.pack(side="bottom", fill="x", pady=(4, 0))
    lb = tk.Listbox(left, selectmode="extended", exportselection=False)
    sb = ttk.Scrollbar(left, command=lb.yview); lb.config(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True); sb.pack(side="left", fill="y")
    selected = set()
    shown = []

    def refresh_list(*_):
        lb.delete(0, "end"); shown.clear()
        if not st["meta"]:
            return
        q = search.get().lower()
        for n, l in zip(st["meta"].column_names, st["meta"].column_labels):
            if q in n.lower() or q in (l or "").lower():
                shown.append(n); lb.insert("end", f"{n}  —  {l or ''}")
                if n in selected:
                    lb.selection_set("end")

    def on_select(_):
        cur = {shown[i] for i in lb.curselection()}
        selected.difference_update(set(shown) - cur); selected.update(cur)
        count_var.set(f"{len(selected)} selected")

    lb.bind("<<ListboxSelect>>", on_select)
    search.trace_add("write", refresh_list)
    count_var = tk.StringVar(value="0 selected")

    # --- filters
    right = ttk.LabelFrame(body, text="Select cases", padding=6)
    right.grid(row=0, column=1, sticky="nsew")
    country = labelled(right, "Country codes (e.g. SE,NO)", 0)
    country_v = labelled(right, "   country variable", 1)
    age = labelled(right, "Age range (e.g. 18-65)", 2)
    age_v = labelled(right, "   age variable", 3)
    gender = labelled(right, "Gender code(s) (e.g. 2)", 4)
    gender_v = labelled(right, "   gender variable", 5)
    where = labelled(right, "Other filter (VAR=VALUES)", 6)
    ttk.Separator(right).grid(row=7, columnspan=2, sticky="we", pady=6)
    ncases = labelled(right, "Number of cases (blank = all)", 8)
    mode = tk.StringVar(value="random")
    ttk.Radiobutton(right, text="Random sample", variable=mode, value="random").grid(row=9, column=0, sticky="w")
    ttk.Radiobutton(right, text="First N cases", variable=mode, value="first").grid(row=9, column=1, sticky="w")
    seed = labelled(right, "Random seed", 10); seed.set("12345")
    ttk.Label(right, textvariable=count_var).grid(row=11, column=0, sticky="w", pady=(10, 0))

    def show_values(v):
        name = v.get().strip()
        if st["path"] and name:
            try:
                df, _ = pyreadstat.read_sav(st["path"], usecols=[name])
                labs = st["meta"].variable_value_labels.get(name, {})
                txt = "\n".join(f"{c}: {k:,}  {labs.get(c, '')}"
                                for c, k in df[name].value_counts().sort_index().items())
                messagebox.showinfo(f"Values of {name}", txt[:3000] or "(no values)")
            except Exception as e:
                messagebox.showerror("Error", str(e))
    for r, v in ((1, country_v), (3, age_v), (5, gender_v)):
        ttk.Button(right, text="values", width=7, command=lambda v=v: show_values(v)).grid(row=r, column=2)

    # --- log + run
    bottom = ttk.Frame(root, padding=8); bottom.pack(fill="x")
    logbox = tk.Text(bottom, height=8); logbox.pack(fill="x")

    q = queue.Queue()     # worker thread -> GUI (Tk itself is not thread-safe)

    def log(*args, end="\n", **_):
        q.put(("log", " ".join(map(str, args)) + ("\n" if end == "\r" else end)))

    def poll():
        while not q.empty():
            kind, payload = q.get()
            if kind == "log":
                logbox.insert("end", payload); logbox.see("end")
            elif kind == "done":
                run_btn.config(state="normal")
                (messagebox.showinfo if payload[0] else messagebox.showerror)(*payload[1:])
        root.after(100, poll)

    def open_file():
        path = filedialog.askopenfilename(filetypes=[("SPSS data", "*.sav *.zsav"), ("All", "*.*")])
        if not path:
            return
        try:
            st["meta"] = read_meta(path); st["path"] = path
        except Exception as e:
            messagebox.showerror("Could not open file", str(e)); return
        file_var.set(f"{os.path.basename(path)}  —  {st['meta'].number_rows or '?'} cases, "
                     f"{st['meta'].number_columns} variables")
        selected.clear(); refresh_list()
        for kind, v in (("country", country_v), ("age", age_v), ("gender", gender_v)):
            v.set(detect_var(st["meta"], kind) or "")

    def run():
        if not st["path"]:
            messagebox.showwarning("No file", "Open a .sav file first."); return
        out = filedialog.asksaveasfilename(
            defaultextension=".sav",
            initialfile=os.path.splitext(os.path.basename(st["path"]))[0] + "_subset.sav",
            filetypes=[("SPSS", "*.sav"), ("CSV", "*.csv"), ("Excel", "*.xlsx"), ("Stata", "*.dta")])
        if not out:
            return
        order = [n for n in st["meta"].column_names if n in selected]
        try:
            n = int(ncases.get()) if ncases.get().strip() else None
            sd = int(seed.get() or 12345)
        except ValueError:
            messagebox.showerror("Error", "Number of cases and seed must be whole numbers."); return
        kw = dict(variables=",".join(order) or None, country=country.get().strip() or None,
                  age=age.get().strip() or None, gender=gender.get().strip() or None,
                  where=[where.get().strip()] if where.get().strip() else None,
                  country_var=country_v.get().strip() or None, age_var=age_v.get().strip() or None,
                  gender_var=gender_v.get().strip() or None, n=n, first=mode.get() == "first", seed=sd)
        run_btn.config(state="disabled")

        def work():
            try:
                select(st["path"], out, log=log, **kw)
                q.put(("done", (True, "Done", f"Saved to\n{out}")))
            except Exception as e:
                log("ERROR:", e)
                q.put(("done", (False, "Error", str(e))))
        threading.Thread(target=work, daemon=True).start()

    ttk.Button(btns, text="Clear selection",
               command=lambda: (selected.clear(), refresh_list(), count_var.set("0 selected"))).pack(side="left")
    run_btn = ttk.Button(bottom, text="Select and save…", command=run)
    run_btn.pack(pady=(6, 0))
    poll()
    root.mainloop()


def main():
    for stream in (sys.stdout, sys.stderr):   # Windows consoles can't show every character
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    if len(sys.argv) > 1:
        try:
            cli(sys.argv[1:])
        except (ValueError, FileNotFoundError, pyreadstat.ReadstatError) as e:
            sys.exit(f"Error: {e}")
    else:
        gui()


if __name__ == "__main__":
    main()
