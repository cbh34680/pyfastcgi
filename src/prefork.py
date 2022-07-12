import pyfastcgi
import pyfastcgi.util.multiprocess
import pyfastcgi.listener


def main():
    config = pyfastcgi.parse_args()
    context = pyfastcgi.util.multiprocess.make_context(config)
    pyfastcgi.listener.start(context)


if __name__ == '__main__':
    main()

# EOF
