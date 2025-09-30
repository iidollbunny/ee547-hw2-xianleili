#!/bin/bash

# Test 1: Machine Learning papers
./run.sh "cat:cs.LG" 5 output_ml/

# Test 2: Search by author
./run.sh "au:LeCun" 3 output_author/

# Test 3: Search by title keyword
./run.sh "ti:transformer" 10 output_title/

# Test 4: Complex query
./run.sh "cat:cs.LG AND ti:transformer AND submittedDate:[20220101 TO 20230101]" 5 output_complex/

echo "Test completed. Check output directories for results."
