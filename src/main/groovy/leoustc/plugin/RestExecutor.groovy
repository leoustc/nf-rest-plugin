package leoustc.plugin
import nextflow.executor.Executor
import nextflow.processor.TaskHandler
import nextflow.processor.TaskMonitor
import nextflow.processor.TaskPollingMonitor
import nextflow.processor.TaskRun
import nextflow.util.Duration
import nextflow.util.ServiceName
import org.pf4j.Extension
import org.slf4j.Logger
import org.slf4j.LoggerFactory

import java.net.URI
import java.net.http.HttpClient
import java.util.ArrayList
import java.util.Collection
import java.util.Collections
@ServiceName('rest')
@Extension
class RestExecutor extends Executor {

    private static final Logger log = LoggerFactory.getLogger(RestExecutor)

    public static final String DEFAULT_ENDPOINT = 'http://localhost:8080'
    public static final String CFG_ENDPOINT = 'endpoint'
    public static final String CFG_API_KEY = 'api_key'

    private final HttpClient httpClient
    private final URI serviceUri
    private final String apiKey
    private volatile URI resolvedServiceUri
    private final Duration defaultPollInterval = Duration.of('2 sec')

    RestExecutor() {
        this.serviceUri = URI.create(DEFAULT_ENDPOINT)
        this.apiKey = null
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(java.time.Duration.ofSeconds(5))
                .version(HttpClient.Version.HTTP_1_1)
                .build()
    }

    @Override
    protected TaskMonitor createTaskMonitor() {
        final Duration pollDuration = restPollDuration()
        return TaskPollingMonitor.create(getSession(), getConfig(), getName(), pollDuration)
    }

    @Override
    TaskHandler createTaskHandler(final TaskRun task) {
        return new RestTaskHandler(task, this)
    }

    URI jobsUri() {
        return getServiceUri().resolve('/jobs')
    }

    URI jobUri(final String jobId) {
        return getServiceUri().resolve("/jobs/${jobId}".toString())
    }

    URI killUri(final String jobId) {
        return getServiceUri().resolve("/jobs/${jobId}/kill".toString())
    }

    HttpClient getHttpClient() {
        return httpClient
    }

    java.time.Duration statusPollPeriod() {
        final Duration pollDuration = restPollDuration()
        return java.time.Duration.ofMillis(pollDuration.toMillis())
    }

    Map<String,Object> getSessionConfig() {
        def s = getSession()
        if( !s )
            return null
        final Object cfg = s.getConfig()
        return (Map<String,Object>) cfg
    }

    String getSessionWorkDir() {
        def s = getSession()
        final Object p = s != null ? s.getWorkDir() : null
        return p != null ? p.toString() : null
    }

    String getSessionOutputDir() {
        def s = getSession()
        final Object p = s != null ? s.getOutputDir() : null
        return p != null ? p.toString() : null
    }

    String getSessionBucketDir() {
        def s = getSession()
        final Object p = s != null ? s.getBucketDir() : null
        return p != null ? p.toString() : null
    }

    String getSessionBaseDir() {
        def s = getSession()
        final Object p = s != null ? s.getBaseDir() : null
        return p != null ? p.toString() : null
    }

    String getParamOutdir() {
        final Map<String,Object> cfg = getSessionConfig()
        if( cfg == null )
            return null
        final Object paramsObj = cfg.get('params')
        if( !(paramsObj instanceof Map) )
            return null
        final Map<?,?> params = (Map<?,?>) paramsObj
        final Object outdir = params.get('outdir')
        return outdir != null ? outdir.toString() : null
    }

    List<String> getParamInputs() {
        final Map<String,Object> cfg = getSessionConfig()
        if( cfg == null )
            return Collections.emptyList()
        final Object paramsObj = cfg.get('params')
        if( !(paramsObj instanceof Map) )
            return Collections.emptyList()
        final Map<?,?> params = (Map<?,?>) paramsObj
        final Object inputObj = params.get('input')
        if( inputObj == null )
            return Collections.emptyList()

        final List<String> result = new ArrayList<>()
        if( inputObj instanceof Collection ) {
            for( Object value : (Collection<?>) inputObj ) {
                if( value != null ) {
                    result.add(value.toString())
                }
            }
        }
        else {
            result.add(inputObj.toString())
        }

        return result
    }

    Duration getRestPollInterval() {
        return restPollDuration()
    }

    private Duration restPollDuration() {
        final Duration restConfig = readRestPollIntervalFromConfig()
        if (restConfig != null) {
            return restConfig
        }
        return getConfig()?.getPollInterval(getName(), defaultPollInterval) ?: defaultPollInterval
    }

    private Duration readRestPollIntervalFromConfig() {
        try {
            final Object cfgRoot = getSession()?.getConfig()
            if (cfgRoot instanceof Map) {
                final Map<?,?> root = (Map<?,?>) cfgRoot
                final Object restCfg = root.get('rest')
                if (restCfg instanceof Map) {
                    final Object value = ((Map<?,?>)restCfg).get('pollInterval')
                    if (value instanceof Duration) {
                        return (Duration) value
                    }
                    if (value instanceof CharSequence) {
                        try {
                            return Duration.of(value.toString())
                        }
                        catch (Exception ignored) {
                            // ignore invalid format
                        }
                    }
                    if (value instanceof Number) {
                        return Duration.ofMillis(((Number)value).longValue())
                    }
                }
            }
        }
        catch (Throwable ignored) {
            // fall back to defaults below
        }
        return null
    }

    private URI computeServiceUri() {
        // Prefer top-level `rest { endpoint = ... }` config
        String configured = null
        try {
            final Object cfgRoot = getSession()?.getConfig()
            if (cfgRoot instanceof Map) {
                final Map<?,?> root = (Map<?,?>) cfgRoot
                final Object restCfg = root.get('rest')
                if (restCfg instanceof Map) {
                    configured = (String) ((Map<?,?>)restCfg).get(CFG_ENDPOINT)
                }
            }
        }
        catch (Throwable ignored) {
            // fall back to defaults below
        }

        if (configured) {
            return URI.create(configured)
        }
        return serviceUri
    }

    URI getServiceUri() {
        if (resolvedServiceUri == null) {
            synchronized (this) {
                if (resolvedServiceUri == null) {
                    resolvedServiceUri = computeServiceUri()
                }
            }
        }
        return resolvedServiceUri
    }

    String getApiKey() {
        // Prefer top-level `rest { api_key = ... }` config
        String configured = null
        try {
            final Object cfgRoot = getSession()?.getConfig()
            if (cfgRoot instanceof Map) {
                final Map<?,?> root = (Map<?,?>) cfgRoot
                final Object restCfg = root.get('rest')
                if (restCfg instanceof Map) {
                    configured = (String) ((Map<?,?>)restCfg).get(CFG_API_KEY)
                }
            }
        }
        catch (Throwable ignored) {
            // fall back to defaults below
        }

        if (configured) {
            final String masked = configured.length() > 4 ? configured[0..1] + '***' + configured[-2..-1] : '***'
            // log.info("RestExecutor using configured api_key from 'rest { api_key = ... }': {}", masked)
            return configured
        }

        log.info("RestExecutor api_key not configured; no authentication header will be sent")
        return apiKey
    }
}
