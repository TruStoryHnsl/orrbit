# Gunicorn configuration for orrbit

bind = '0.0.0.0:5000'
workers = 1
worker_class = 'gevent'
worker_connections = 200
timeout = 0  # No timeout (long-running thumbnail generation)
accesslog = '-'
errorlog = '-'
loglevel = 'info'


def post_worker_init(worker):
    """Increase gevent threadpool after worker starts.

    Default is 10 threads — too low when NFS scans overlap with
    route handlers using run_in_real_thread(). Match orrapus at 50.
    """
    from gevent import get_hub
    get_hub().threadpool.maxsize = 50
    print(f'[gunicorn] gevent threadpool maxsize set to {get_hub().threadpool.maxsize}')
