package leoustc.plugin

import groovy.transform.CompileStatic
import nextflow.plugin.BasePlugin
import org.pf4j.PluginWrapper

@CompileStatic
class RestExecutorPlugin extends BasePlugin {
    RestExecutorPlugin(PluginWrapper wrapper) {
        super(wrapper)
    }
}
