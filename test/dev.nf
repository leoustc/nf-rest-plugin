nextflow.enable.dsl=2
// ------------------
// Processes
// ------------------
process CountLines {
    cpus 1
    memory '2 GB'
    accelerator 1, type: 'VM.Standard.E5.Flex'
    disk '200 GB'
    publishDir params.outdir, mode: 'copy'

    input:
    path infile

    output:
    path 'result/*.count'

    script:
    """
    mkdir -p result
    localname=\$(basename "${infile}")
    count=\$(wc -l "${infile}" | awk '{print \$1}')
    echo "\${count}" > result/\${localname}.\${count}.count
    """
}

// ------------------
// Workflow
// ------------------
workflow {
    // Base input channel
    ch_in = Channel.fromPath(params.input)
    CountLines(ch_in)
}
