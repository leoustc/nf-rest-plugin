nextflow.enable.dsl=2

// ------------------
// Processes
// ------------------

// A: start from file input
process A {
    cpus 1
    memory '1 GB'

    tag "${sample.baseName}"

    input:
    path sample

    output:
    path "*.txt"

    script:
    """
    in_file=\$(basename "${sample}")
    echo "A got: \${in_file}" > a_\${in_file}.txt
    """
}

// B: independent fan‑out (names only)
process B {
    cpus 2
    memory '4 GB'
    accelerator 1, type: 'VM.GPU.A10.1'

    tag "B-GPU-${x}"
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

// C: depends on A output
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

// D: independent, long‑running (names only)
process D {
    cpus 2
    memory '6 GB'

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
    cpus 6
    memory '12 GB'

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
        .fromPath(params.input)
        .set { ch_files }

    // Derive simple names for branches B and D
    ch_names = ch_files.map { it.baseName }

    // Fan‑out branches
    ch_a_out = A(ch_files)
    ch_b_out = B(ch_names)
    ch_d_out = D(ch_names)

    // Chained branch A -> C -> E
    ch_c_out = C(ch_a_out)
    ch_e_out = E(ch_c_out)

    // Simple logging of outputs
    ch_b_out.view { "B output: ${it}" }
    ch_d_out.view { "D output: ${it}" }
    ch_e_out.view { "E output: ${it}" }
}
