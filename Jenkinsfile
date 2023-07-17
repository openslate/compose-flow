@Library('OpenSlateProd')_  // https://github.com/openslate/jenkins-shared-library

def customPublishTask = {
    cfPublish()
    sh "compose-flow -e ${env.DEPLOY_ENV} --project-name ${env.REPO_NAME} compose run -u root:docker --rm app /bin/bash ./scripts/publish.sh"
}

def publishWhen = { env.TAG_NAME }

openslatePipeline {
    mentions = '<@U02SGRQEKFY>'
    deployEnv = 'prod'
    lint = true
    test = true
    publish = publishWhen
    publishFunction = customPublishTask
    deploy = false
}
