nextflow.enable.dsl=2

// ------------------
// Parameters
// ------------------
params.input  = [ 'one', 'two', 'three' ]
params.outdir = params.outdir ?: 's3://nf-data/results'

// ------------------
// Processes
// ------------------

// A: start of the chain
process A {
    cpus 1
    memory '1 GB'
    accelerator 1, type: 'VM.GPU.A10.1'  // GPU Supported (will be ignored if executor doesn't support it)
    input:
    val x

    output:
    path "a_${x}.txt"

    script:
    """
    echo "A got: ${x}" > a_${x}.txt
    """
}

// B: independent, runs in parallel
process B {
    cpus 2
    memory '4 GB'

    publishDir params.outdir, mode: 'copy'

    input:
    val x

    output:
    path "b_${x}.txt"

    script:
    """
    sleep 10
    echo "B got: ${x}" > b_${x}.txt
    """
}

// C: depends on A
process C {
    cpus 4
    memory '8 GB'
    // accelerator 1, type: 'VM.GPU.A10.1'
    input:
    path from_a

    output:
    path "c_*"

    script:
    """
    in_file=\$(basename "${from_a}")
    sleep 5
    echo "C processed: \${in_file}" > "c_\${in_file}"
    """
}

// D: independent, runs in parallel
process D {
    cpus 2
    memory '8 GB'

    publishDir params.outdir, mode: 'copy'

    input:
    val x

    output:
    path "d_${x}.txt"

    script:
    """
    sleep 20
    echo "D got: ${x}" > d_${x}.txt
    """
}

// E: depends on C (so A -> C -> E)
process E {
    cpus 4
    memory '6 GB'
    // accelerator 1, type: 'VM.GPU.A10.1'

    publishDir params.outdir, mode: 'copy'

    input:
    path from_c

    output:
    path "e_*"

    script:
    """
    in_file=\$(basename "${from_c}")
    sleep 10
    echo "E processed: \${in_file}" > "e_\${in_file}"
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
    ch_b_out = B(ch_in)
    ch_d_out = D(ch_in)

    // C depends on A
    ch_c_out = C(ch_a_out)

    // E depends on C
    ch_e_out = E(ch_c_out)

    // Example: collect/print all results
    ch_b_out.view { "B output: ${it}" }
    ch_d_out.view { "D output: ${it}" }
    ch_e_out.view { "E output: ${it}" }
}
