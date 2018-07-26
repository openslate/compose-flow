LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
        },
    },

    'loggers': {
        'compose_flow': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },

    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
        'propagate': True,
    },
}
