def handler(context, event):
    context.logger.info('This is an unstructured log')
    return 'Hello, from Nuclio :]'
