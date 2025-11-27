nextflow.enable.dsl=2

// ------------------
// Parameters (pipeline defaults)
// ------------------
params.samples = params.samples ?: ['one', 'two', 'three']
params.outdir  = params.outdir  ?: 's3://nf-data/results'

// ------------------
// Processes
// ------------------

// A: simple preparation step
process A {
    cpus 1
    memory '1 GB'

    tag "${x}"

    input:
    val x

    output:
    path "a_${x}.txt"

    script:
    """
    echo "A got: ${x}" > a_${x}.txt
    """
}

// B: independent fan‑out
process B {
    cpus 2
    memory '4 GB'

    tag "B-${x}"
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

    tag "C-${from_a.baseName}"

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

// D: independent, long‑running
process D {
    cpus 2
    memory '8 GB'

    tag "D-${x}"
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

// E: final aggregation from C (A -> C -> E)
process E {
    cpus 4
    memory '6 GB'

    tag "E-${from_c.baseName}"
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
    Channel
        .fromList(params.samples)
        .set { ch_samples }

    // Fan‑out branches
    ch_a_out = A(ch_samples)
    ch_b_out = B(ch_samples)
    ch_d_out = D(ch_samples)

    // Chained branch A -> C -> E
    ch_c_out = C(ch_a_out)
    ch_e_out = E(ch_c_out)

    // Simple logging of outputs
    ch_b_out.view { "B output: ${it}" }
    ch_d_out.view { "D output: ${it}" }
    ch_e_out.view { "E output: ${it}" }
}
