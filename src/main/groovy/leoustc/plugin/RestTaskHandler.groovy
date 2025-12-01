package leoustc.plugin

import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import nextflow.executor.BashWrapperBuilder
import nextflow.executor.res.AcceleratorResource
import nextflow.file.FileHolder
import nextflow.processor.PublishDir
import nextflow.processor.TaskConfig
import nextflow.processor.TaskHandler
import nextflow.processor.TaskRun
import nextflow.processor.TaskStatus
import nextflow.util.Duration as NxfDuration
import nextflow.util.MemoryUnit
import org.slf4j.Logger
import org.slf4j.LoggerFactory

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.nio.file.Path
import java.time.Duration
import java.time.Instant
import java.util.ArrayList
import java.util.Collection
import java.util.LinkedHashSet
import java.util.LinkedHashMap
import java.util.List
import java.util.Map
import java.util.Collections
class RestTaskHandler extends TaskHandler {

    private static final Logger log = LoggerFactory.getLogger(RestTaskHandler)

    private final RestExecutor executor
    private final HttpClient client
    private final JsonSlurper jsonSlurper = new JsonSlurper()
    private final Duration pollDelay
    private final Path workDir

    private String jobId
    private Instant lastPoll = Instant.EPOCH
    private Map<String, Object> lastStatus = Collections.emptyMap()

    RestTaskHandler(final TaskRun task, final RestExecutor executor) {
        super(task)
        this.executor = executor
        this.client = executor.httpClient
        this.pollDelay = executor.statusPollPeriod()
        this.workDir = task.getWorkDir()
    }

    @Override
    void submit() {
        buildTaskWrapper()

        // original workdir as seen by Nextflow (may be s3://...)
        final String originalWorkPath = workDir.toString()

        final URI serviceUri = executor.getServiceUri()
        final NxfDuration pollInterval = executor.getRestPollInterval()
        log.info(
                '[submit] RestExecutor service URI={} workdir={} pollInterval={}',
                serviceUri,
                originalWorkPath,
                pollInterval
        )

        final String workPath = originalWorkPath

        final Map<String, ?> payload = [
                command : "bash ${TaskRun.CMD_RUN}".toString(),
                workdir : workPath,
                env     : Collections.emptyMap(),
                storage : buildStorageConfig(originalWorkPath),
                resources: collectResources(),
                metadata: buildMetadata(originalWorkPath, workPath)
        ]

        final String json = JsonOutput.toJson(payload)
        if( log.isDebugEnabled() ) {
            log.debug('REST executor POST payload: {}', json)
        }
        final byte[] jsonBytes = json.getBytes(StandardCharsets.UTF_8)
        final HttpRequest request = newRequestBuilder(executor.jobsUri())
                .header('Content-Type', 'application/json')
                .POST(HttpRequest.BodyPublishers.ofByteArray(jsonBytes))
                .build()

        final Map<String, Object> response = send(request)
        this.jobId = response.job_id as String

        if (!jobId) {
            throw new IllegalStateException("REST executor did not return a job_id for ${taskName()}")
        }

        setStatus(TaskStatus.SUBMITTED)
        setSubmitTimeMillis(System.currentTimeMillis())
    }

    @Override
    boolean checkIfRunning() {
        refreshStatus()
        final String state = (String) (lastStatus?.get('status') ?: '')
        if (state == 'running') {
            if (!isRunning()) {
                setStatus(TaskStatus.RUNNING)
                setStartTimeMillis(System.currentTimeMillis())
            }
            return true
        }
        return false
    }

    @Override
    boolean checkIfCompleted() {
        refreshStatus()
        final String state = (String) (lastStatus?.get('status') ?: '')
        if (state in ['finished', 'failed', 'killed']) {
            final Integer exitCode = parseReturnCode(lastStatus?.get('returncode'))
            if (exitCode != null) {
                getTask().setExitStatus(exitCode)
            }
            final Object stdout = lastStatus?.get('stdout')
            if (stdout instanceof CharSequence) {
                getTask().setStdout(stdout.toString())
            }
            final Object stderr = lastStatus?.get('stderr')
            if (stderr instanceof CharSequence) {
                getTask().setStderr(stderr.toString())
            }

            setStatus(TaskStatus.COMPLETED)
            setCompleteTimeMillis(System.currentTimeMillis())
            return true
        }
        return false
    }

    @Override
    void kill() {
        if (!jobId) {
            return
        }
        final HttpRequest request = newRequestBuilder(executor.killUri(jobId))
                .POST(HttpRequest.BodyPublishers.noBody())
                .build()
        send(request, true)
    }

    private void refreshStatus() {
        if (!jobId) {
            return
        }

        final Instant now = Instant.now()
        if (now.isBefore(lastPoll.plus(pollDelay))) {
            return
        }

        final HttpRequest request = newRequestBuilder(executor.jobUri(jobId))
                .GET()
                .build()

        this.lastStatus = send(request, true)
        this.lastPoll = now
    }

    private Map<String, Object> send(final HttpRequest request) {
        return send(request, false)
    }

    private Map<String, Object> send(final HttpRequest request, final boolean allowNotFound) {
        try {
            final HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString())
            final int code = response.statusCode()
            final Map<String, Object> parsedBody = parseJsonBody(response.body())
            if (code == 404 && allowNotFound) {
                final Map<String, Object> missing = new LinkedHashMap<>()
                missing.put('status', 'failed')
                missing.put('returncode', 1)
                final Object detail = parsedBody?.get('detail') ?: parsedBody?.get('message')
                final String msg = detail ? detail.toString() : "Job not found (${request.uri()})"
                missing.put('stderr', msg)
                log.warn('REST executor {} {} returned 404: {}; treating as failed', request.method(), request.uri(), msg)
                return missing
            }
            if (code >= 300) {
                throw new IllegalStateException("REST executor ${request.method()} ${request.uri()} failed with ${code}: ${response.body()}")
            }
            return parsedBody
        }
        catch (InterruptedException ie) {
            Thread.currentThread().interrupt()
            throw new IllegalStateException("REST executor request interrupted for ${request.uri()}", ie)
        }
        catch (Exception e) {
            throw new IllegalStateException("REST executor request failed for ${request.uri()}", e)
        }
    }

    private void buildTaskWrapper() {
        log.debug('Building wrapper for REST task {} in {}', taskName(), workDir)
        new BashWrapperBuilder(getTask()).build()
    }

    private Map<String, Object> collectResources() {
        final TaskConfig cfg = getTask()?.getConfig()
        final Integer cpu = (cfg?.getCpus() instanceof Number) ? ((Number) cfg.getCpus()).intValue() : null
        final MemoryUnit mem = cfg?.getMemory()
        final Long ramGiga = mem ? mem.toGiga() : null
        final MemoryUnit disk = cfg?.getDisk()
        final Long diskGiga = disk ? disk.toGiga() : null

        final AcceleratorResource accelerator = cfg?.getAccelerator()
        final Integer acceleratorCount = accelerator?.getRequest()
        final String acceleratorType = accelerator?.getType()

        final Map<String, Object> resources = new LinkedHashMap<>()

        resources.put('cpu', cpu)
        resources.put('ram', ramGiga)
        resources.put('disk', diskGiga)

        if (acceleratorCount == null) {
            resources.put('accelerator', 0)
        } else {
            resources.put('accelerator', acceleratorCount)
        }
        resources.put('shape', acceleratorType)

        return resources
    }

    private Map<String, Object> buildMetadata(final String originalWorkPath, final String workPath) {
        final Map<String, Object> meta = new LinkedHashMap<>()

        meta.put('process', taskName())
        meta.put('taskId', getTask()?.getId()?.toString())
        meta.put('workdir', workPath)
        if( originalWorkPath != null ) {
            meta.put('originalWorkdir', originalWorkPath)
        }
        final String sessionWorkDir = executor.getSessionWorkDir()
        if( sessionWorkDir ) {
            meta.put('sessionWorkDir', sessionWorkDir)
        }
        final String outputDir = executor.getSessionOutputDir()
        if( outputDir ) {
            meta.put('sessionOutputDir', outputDir)
        }
        final String bucketDir = executor.getSessionBucketDir()
        if( bucketDir ) {
            meta.put('sessionBucketDir', bucketDir)
        }

        final String baseDir = executor.getSessionBaseDir()
        if( baseDir ) {
            meta.put('projectDir', baseDir)
        }

        final String outdir = executor.getParamOutdir()
        if( outdir ) {
            meta.put('paramsOutdir', outdir)
        }

        final Map<String,String> taskInput = findTaskInputWithType()
        if( taskInput?.get('value') ) {
            meta.put('paramsInput', Collections.singletonList(taskInput.get('value')))
            meta.put('paramsInputType', taskInput.get('type'))
        }
        else {
            final List<String> paramsInput = executor.getParamInputs()
            if( paramsInput ) {
                meta.put('paramsInput', Collections.singletonList(paramsInput.get(0)))
                meta.put('paramsInputType', 'config')
            }
        }

        final TaskConfig cfg = getTask()?.getConfig()
        final Object publishObj = cfg != null ? cfg.getPublishDir() : null
        if( publishObj instanceof Collection ) {
            final List<String> publishDirs = new ArrayList<>()
            for( PublishDir pd : (Collection<PublishDir>)publishObj ) {
                try {
                    final Object p = pd.getPath()
                    if( p != null ) {
                        publishDirs.add(p.toString())
                    }
                }
                catch( Throwable ignored ) {
                    // ignore
                }
            }
            if( !publishDirs.isEmpty() ) {
                meta.put('publishDirs', publishDirs)
            }
        }

        return meta
    }

    private Map<String,String> findTaskInputWithType() {
        final TaskRun task = getTask()
        if( task == null )
            return null

        // Prefer staged input map for this task
        final Map<String,Path> inputMap = task.getInputFilesMap()
        if( inputMap != null && !inputMap.isEmpty() ) {
            final Path first = inputMap.values().iterator().next()
            if( first != null ) {
                return [value: first.toString(), type: 'file']
            }
        }

        final Object inputFilesObj = task.getInputFiles()
        if( !(inputFilesObj instanceof Map) )
            return null

        final Map<?,?> inputFiles = (Map<?,?>) inputFilesObj
        if( inputFiles.isEmpty() )
            return null

        for( Object value : inputFiles.values() ) {
            final String found = findInputSource(value)
            if( found ) {
                return [value: found, type: 'file']
            }
        }
        return null
    }

    private Map<String, Object> parseJsonBody(final String body) {
        if (body == null || body.isEmpty()) {
            return Collections.emptyMap()
        }
        return (Map<String, Object>) jsonSlurper.parseText(body)
    }

    private String findInputSource(final Object value) {
        if( value == null )
            return null
        if( value instanceof FileHolder ) {
            final FileHolder holder = (FileHolder) value
            final Object source = holder.getSourceObj()
            if( source != null ) {
                return source.toString()
            }
            final Path store = holder.getStorePath()
            if( store != null ) {
                return store.toString()
            }
            return null
        }
        if( value instanceof Collection ) {
            for( Object item : (Collection<?>) value ) {
                final String found = findInputSource(item)
                if( found )
                    return found
            }
        }
        return null
    }

    private Map<String, Object> buildStorageConfig(final String originalWorkPath) {
        final Map<String,Object> result = new LinkedHashMap<>()

        final Map<String,Object> cfg = executor.sessionConfig
        final Map<String,Object> aws = (Map<String,Object>) (cfg != null ? cfg.get('aws') : null)
        if( aws != null ) {
            final Map<String,Object> client = (Map<String,Object>) (aws.get('client') ?: Collections.emptyMap())
            final Object endpoint = client.get('endpoint')
            final Object region = aws.get('region')
            final Object bucket = aws.containsKey('bucket') ? aws.get('bucket') : aws.get('user_param')
            final Object accessKey = aws.get('accessKey')
            final Object secretKey = aws.get('secretKey')

            if( endpoint != null ) {
                result.put('endpoint', endpoint.toString())
            }
            if( region != null ) {
                result.put('region', region.toString())
            }
            if( bucket != null ) {
                result.put('bucket', bucket.toString())
            }
            if( accessKey != null ) {
                result.put('accessKey', accessKey.toString())
            }
            if( secretKey != null ) {
                result.put('secretKey', secretKey.toString())
            }
        }

        if( originalWorkPath != null && originalWorkPath.startsWith('s3://') ) {
            result.put('s3_workdir', originalWorkPath)
        }

        return result
    }

    private String taskName() {
        return getTask()?.getProcessor()?.getName() ?: getTask()?.getName() ?: 'rest-task'
    }

    private static Integer parseReturnCode(final Object value) {
        if (value instanceof Number) {
            return ((Number)value).intValue()
        }
        if (value instanceof CharSequence) {
            try {
                return Integer.parseInt(value.toString())
            }
            catch (NumberFormatException ignored) {
                return null
            }
        }
        return null
    }

    private static Integer toInteger(final Object value) {
        if (value instanceof Number) {
            return ((Number)value).intValue()
        }
        if (value instanceof CharSequence) {
            try {
                return Integer.parseInt(value.toString())
            }
            catch (NumberFormatException ignored) {
                return null
            }
        }
        return null
    }

    private HttpRequest.Builder newRequestBuilder(final URI uri) {
        final HttpRequest.Builder builder = HttpRequest.newBuilder(uri)
        final String apiKey = executor.getApiKey()
        if (apiKey) {
            builder.header('X-API-Key', apiKey)
        }
        return builder
    }
}
