nextflow.enable.dsl=2
// ------------------
// Parameters
// ------------------
params.input  = [ 'one' ]
params.outdir = 's3://nf-data/results'

// ------------------
// Processes
// ------------------
// A: start of the chain
process A {
    cpus 4
    memory '12 GB'
    //accelerator 1, type: 'A10'  // GPU Supported (will be ignored if executor doesn't support it)
    disk '2 TB'                // start disk size, if failed will double automatically, up to max disk size default 32 TB
    //max_disk '100 GB'           // max disk size, max disk size for auto scaling
    //max_retries 3               // retry up to 3 times if process fails

    input:
    val x

    output:
    path "a_${x}.txt"

    script:
    """
    echo "A got: ${x}" > a_${x}.txt
    """
}

// ------------------
// Workflow
// ------------------
workflow {
    // Base input channel
    ch_in = Channel.fromList(params.input)
    // A, B, D all start from the same input and run in parallel
    ch_a_out = A(ch_in)
}