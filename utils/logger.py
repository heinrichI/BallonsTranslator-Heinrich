import datetime
import logging
import os
import os.path as osp
from glob import glob
import termcolor


if os.name == "nt":  # Windows
    import colorama
    colorama.init()


COLORS = {
    "WARNING": "yellow",
    "INFO": "white",
    "DEBUG": "blue",
    "CRITICAL": "red",
    "ERROR": "red",
}


class ColoredFormatter(logging.Formatter):
    def __init__(self, fmt, use_color=True):
        logging.Formatter.__init__(self, fmt)
        self.use_color = use_color

    def format(self, record):
        levelname = record.levelname
        if self.use_color and levelname in COLORS:

            def colored(text):
                try:
                    return termcolor.colored(
                        text,
                        color=COLORS[levelname],
                        attrs={"bold": True},
                    )
                except (ValueError, OSError):
                    return text

            record.levelname2 = colored("{:<7}".format(record.levelname))
            record.message2 = colored(record.getMessage())

            asctime2 = datetime.datetime.fromtimestamp(record.created)
            record.asctime2 = termcolor.colored(asctime2, color="green")

            record.module2 = termcolor.colored(record.module, color="cyan")
            record.funcName2 = termcolor.colored(record.funcName, color="cyan")
            record.lineno2 = termcolor.colored(record.lineno, color="cyan")
        return logging.Formatter.format(self, record)

FORMAT = (
    "[%(levelname2)s] %(module2)s:%(funcName2)s:%(lineno2)s - %(message2)s"
)

class ColoredLogger(logging.Logger):

    def __init__(self, name):
        logging.Logger.__init__(self, name, logging.INFO)

        color_formatter = ColoredFormatter(FORMAT)

        console = logging.StreamHandler()
        console.setFormatter(color_formatter)

        self.addHandler(console)
        return


def setup_logging(logfile_dir: str, max_num_logs=14):

    if not osp.exists(logfile_dir):
        os.makedirs(logfile_dir)
    else:
        old_logs = glob(osp.join(logfile_dir, '*.log'))
        old_logs.sort()
        n_log = len(old_logs)
        if n_log >= max_num_logs:
            to_remove = n_log - max_num_logs + 1
            try:
                for ii in range(to_remove):
                    os.remove(old_logs[ii])
            except Exception as e:
                logger.error(e)

    logfilename = datetime.datetime.now().strftime('_%Y_%m_%d-%H_%M_%S.log')
    logfilep = osp.join(logfile_dir, logfilename)
    fh = logging.FileHandler(logfilep, mode='w', encoding='utf-8')
    fh.setFormatter(
        logging.Formatter(
            ("[%(levelname)s] %(module)s:%(funcName)s:%(lineno)s - %(message)s")
        )
    )
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)


logging.setLoggerClass(ColoredLogger)
logger = logging.getLogger('BallonTranslator')
logger.setLevel(logging.DEBUG)
logger.propagate = False


# Suppress noisy third-party loggers globally via LogRecordFactory.
# transformers creates its own StreamHandler → stderr which bypasses
# per-logger filters. The factory intercepts ALL records at creation time.
_NOISY_NAMES = (
    'transformers', 'paddle', 'ppocr', 'Paddle',
    'huggingface_hub', 'filelock', 'urllib3', 'asyncio',
    'configuration_utils', 'processing_utils', 'image_processing_base',
    'image_processing_utils', 'tokenization_utils_base', 'tokenization_auto',
    'modeling_utils', 'feature_extraction_utils',
)

_original_log_record = logging.LogRecord


class _FilteredLogRecord(_original_log_record):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        name = self.name
        mod = self.module
        for prefix in _NOISY_NAMES:
            if name == prefix or name.startswith(prefix + '.') or mod == prefix:
                self.levelno = logging.CRITICAL + 1
                self.msg = ''
                self.args = ()
                return


logging.setLogRecordFactory(_FilteredLogRecord)


# Add _SuppressFiltered to ALL StreamHandlers so silenced records are dropped.
class _SuppressFiltered(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= logging.CRITICAL


_orig_sh_init = logging.StreamHandler.__init__
def _patched_sh_init(self, *args, **kwargs):
    _orig_sh_init(self, *args, **kwargs)
    self.addFilter(_SuppressFiltered())
logging.StreamHandler.__init__ = _patched_sh_init
