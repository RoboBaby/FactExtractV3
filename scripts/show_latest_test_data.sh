#!/bin/bash
# Show the latest generated test data

echo "=== Latest Test Data Directories ==="
find resources/generated_data -type d -name "[0-9]*" -exec ls -ld {} \; | sort -k6,7 | tail -5

echo ""
echo "=== Most Recent Files ==="
find resources/generated_data -type f \( -name "*.jsonl" -o -name "*.json" \) -exec ls -lth {} \; | head -10

echo ""
echo "=== Latest Dataset ==="
LATEST=$(find resources/generated_data -type d -name "[0-9]*" | sort -V | tail -1)
if [ -n "$LATEST" ]; then
    echo "Directory: $LATEST"
    echo "Files:"
    ls -lh "$LATEST"
    echo ""
    echo "Blob count:"
    wc -l "$LATEST/blobs.jsonl" 2>/dev/null || echo "No blobs.jsonl found"
    echo ""
    echo "Metadata:"
    cat "$LATEST/metadata.json" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "No metadata.json found"
else
    echo "No datasets found"
fi

