"""Creates a small SPSS test file, used by the automatic GitHub build to test the program."""
import sys

import numpy as np
import pandas as pd
import pyreadstat

out = sys.argv[1] if len(sys.argv) > 1 else "test.sav"
rng = np.random.default_rng(1)
N = 20_000
df = pd.DataFrame({
    "idno": np.arange(1, N + 1),
    "cntry": rng.choice(["SE", "NO", "DK", "FI"], N),
    "agea": rng.integers(15, 90, N).astype(float),
    "gndr": rng.choice([1.0, 2.0], N),
})
for i in range(1, 6):
    df[f"q{i}"] = rng.integers(1, 6, N).astype(float)

pyreadstat.write_sav(
    df, out,
    column_labels=["ID", "Country", "Age", "Gender"] + [f"Question {i}" for i in range(1, 6)],
    variable_value_labels={"gndr": {1: "Male", 2: "Female"}, "cntry": {"SE": "Sweden", "NO": "Norway"}},
)
print("wrote", out)
