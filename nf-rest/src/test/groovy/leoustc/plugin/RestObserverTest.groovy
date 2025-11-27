package leoustc.plugin

import nextflow.Session
import spock.lang.Specification

/**
 * Implements a basic factory test
 *
 */
class RestObserverTest extends Specification {

    def 'should create the observer instance' () {
        given:
        def factory = new RestFactory()
        when:
        def result = factory.create(Mock(Session))
        then:
        result.size() == 1
        result.first() instanceof RestObserver
    }

}
