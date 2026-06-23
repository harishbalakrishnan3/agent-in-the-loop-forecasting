
1. Generate Diverse Traces
    1. Currently the tools given to decision agent/node are limited to variations of single item like variations of anomaly, changepoint, drift etc. Generate datasets that has all three and the datasets which can't be cleanly forecasted using any of the given tools, for example we can a sinusodial graph which has both predictable outlier like say at multiples of pie/2 and 3pie/2 instead of 1 and -1 is always some higher value which increases also, but at the same time in each sinosudial wave there must be other random noise, now it will be diffcult for the decision node to call any of its given tools. Obviously when u generate the datasets, u need to keep track of the ground truth to compare against the prediction.
    2. Try to get actual datasets used in time series forecast which cant work with existing tools, u are free to download from internet.
    4. In total I need around 100 samples.

2. For each of the 100 samples where the existing agent performs worse, try to fit them into failure mode buckets. Something like 20 samples might fit into failure mode bucket of name 1, and others might be into other failure mode buckets. After going through the trace of these 100 samples, u need to detect differnet types of failure modes.

3. Figure out the failure modes, the evaluator for the same and method. 

4. I want to to able to see the LLM eval changes in Langsmith so code accordingly and use temp/llm-evals-gouthamp-iisc for context and Lecture 11 from this notes/DA225o_Week01_02_Notes.tex.

5. Do all of this in a temp throwaway directory under poc.



For the Generate Diverse Traces ie Dataset creation, firt figure out looking at the codebase and agents what exactly is the input and what is the output. U need to have golden output that is u need to have ground truth for the changepoints and the different stastical details that the diagonistic tool outputs etc.