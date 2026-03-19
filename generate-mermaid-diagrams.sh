#!/usr/bin/env bash

# Process architecture diagrams
for mmd_file in assets/mermaid/architecture/*.mmd; do
    [ -e "$mmd_file" ] || continue
    mmdc -i "$mmd_file" -o "assets/images/architecture/$(basename "$mmd_file" .mmd).png" -b transparent --scale 2
done

# Process data model diagrams
for mmd_file in assets/mermaid/data_models/*.mmd; do
    [ -e "$mmd_file" ] || continue
    mmdc -i "$mmd_file" -o "assets/images/data_models/$(basename "$mmd_file" .mmd).png" -b transparent --scale 2
done
