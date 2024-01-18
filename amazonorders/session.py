import json
import logging
import os
from io import BytesIO
from typing import Optional, Any, Dict
from urllib.parse import urlparse

import requests
from PIL import Image
from amazoncaptcha import AmazonCaptcha
from bs4 import BeautifulSoup, Tag
from requests import Session, Response
from requests.utils import dict_from_cookiejar

from amazonorders.exception import AmazonOrdersAuthError

__author__ = "Alex Laird"
__copyright__ = "Copyright 2024, Alex Laird"
__version__ = "1.0.2"

logger = logging.getLogger(__name__)

BASE_URL = "https://www.amazon.com"
BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "max-age=0",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": BASE_URL,
    "Referer": "{}/ap/signin".format(BASE_URL),
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": "macOS",
    "Sec-Ch-Viewport-Width": "1393",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Viewport-Width": "1393",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
SIGN_IN_FORM_NAME = "signIn"
MFA_DEVICE_SELECT_FORM_ID = "auth-select-device-form"
MFA_FORM_ID = "auth-mfa-form"
CAPTCHA_1_DIV_ID = "cvf-page-content"
CAPTCHA_1_FORM_CLASS = "cvf-widget-form"
CAPTCHA_2_INPUT_ID = "captchacharacters"

DEFAULT_COOKIE_JAR_PATH = os.path.join(os.path.expanduser("~"), ".config", "amazon-orders", "cookies.json")


class IODefault:
    """
    Handles input/output from the application. By default, this uses console commands, but
    this class exists so that it can be overriden when constructing an :class:`AmazonSession`
    if input/output should be handled another way.
    """

    def echo(self, msg):
        """
        Echo a message to the console.

        :param msg: The data to send to output.
        """
        print(msg)

    def prompt(self, msg, type=None):
        """
        Prompt to the console for user input.

        :param msg: The data to use as the input prompt.
        :param type: Unused by the default implementation.
        :return: The user input result.
        """
        return input("{}: ".format(msg))


class AmazonSession:
    """

    """

    def __init__(self,
                 username: str,
                 password: str,
                 debug: bool = False,
                 max_auth_attempts: int = 10,
                 cookie_jar_path: str = None,
                 io: IODefault = IODefault()) -> None:
        if not cookie_jar_path:
            cookie_jar_path = DEFAULT_COOKIE_JAR_PATH

        #: An Amazon username.
        self.username: str = username
        #: An Amazon password.
        self.password: str = password

        #: Set logger ``DEBUG``, send output to ``stderr``, and write an HTML file for each request made on the session.
        self.debug: bool = debug
        if self.debug:
            logger.setLevel(logging.DEBUG)
        #: Will continue in :func:`login()`'s auth flow this many times.
        self.max_auth_attempts: int = max_auth_attempts
        #: The path to persist session cookies, defaults to ``conf.DEFAULT_COOKIE_JAR_PATH``.
        self.cookie_jar_path: str = cookie_jar_path
        #: The I/O handler for echoes and prompts.
        self.io: IODefault = io

        #: The shared session to be used across all requests.
        self.session: Session = Session()
        #: The last response executed on the Session.
        self.last_response: Optional[Response] = None
        #: A parsed representation of the last response executed on the Session.
        self.last_response_parsed: Optional[Tag] = None
        #: If :func:`login()` has been executed and successfully logged in the session.
        self.is_authenticated: bool = False

        cookie_dir = os.path.dirname(self.cookie_jar_path)
        if not os.path.exists(cookie_dir):
            os.makedirs(cookie_dir)
        if os.path.exists(self.cookie_jar_path):
            with open(cookie_jar_path, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
                cookies = requests.utils.cookiejar_from_dict(data)
                self.session.cookies.update(cookies)

    def request(self,
                method: str,
                url: str,
                **kwargs: Any) -> Response:
        """
        Execute the request against Amazon with base headers, parsing and storing the response
        and persisting response cookies.

        :param method: The request method to execute.
        :param url: The URL to execute ``method`` on.
        :param kwargs: Remaining ``kwargs`` will be passed to :func:`requests.request`.
        :return: The Response from the executed request.
        """
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"].update(BASE_HEADERS)

        logger.debug("{} request to {}".format(method, url))

        self.last_response = self.session.request(method, url, **kwargs)
        self.last_response_parsed = BeautifulSoup(self.last_response.text,
                                                  "html.parser")

        cookies = dict_from_cookiejar(self.session.cookies)
        if os.path.exists(self.cookie_jar_path):
            os.remove(self.cookie_jar_path)
        with open(self.cookie_jar_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(cookies))

        logger.debug("Response: {} - {}".format(self.last_response.url,
                                                self.last_response.status_code))

        if self.debug:
            page_name = self._get_page_from_url(self.last_response.url)
            with open(page_name, "w", encoding="utf-8") as html_file:
                logger.debug(
                    "Response written to file: {}".format(html_file.name))
                html_file.write(self.last_response.text)

        return self.last_response

    def get(self,
            url: str,
            **kwargs: Any):
        """
        Perform a GET request.

        :param url: The URL to GET on.
        :param kwargs: Remaining ``kwargs`` will be passed to :func:`AmazonSession.request`.
        :return: The Response from the executed GET request.
        """
        return self.request("GET", url, **kwargs)

    def post(self,
             url,
             **kwargs: Any) -> Response:
        """
        Perform a POST request.

        :param url: The URL to POST on.
        :param kwargs: Remaining ``kwargs`` will be passed to :func:`AmazonSession.request`.
        :return: The Response from the executed POST request.
        """
        return self.request("POST", url, **kwargs)

    def auth_cookies_stored(self):
        cookies = dict_from_cookiejar(self.session.cookies)
        return cookies.get("session-token") and cookies.get("x-main")

    def login(self) -> None:
        """
        Execute an Amazon login process. This will include the sign-in page, and may also include Captcha challenges
        and OTP pages (of 2FA authentication is enabled on your account).

        If successful, ``is_authenticated`` will be set to ``True``.

        Session cookies are persisted, and if existing session data is found during this auth flow, it will be
        skipped entirely and flagged as authenticated.
        """
        self.get("{}/gp/sign-in.html".format(BASE_URL))

        attempts = 0
        while not self.is_authenticated and attempts < self.max_auth_attempts:
            if self.auth_cookies_stored() or \
                    ("Hello, sign in" not in self.last_response.text and
                     "nav-item-signout" in self.last_response.text):
                self.is_authenticated = True
                break

            if self._is_field_found(SIGN_IN_FORM_NAME):
                self._sign_in()
            elif self._is_field_found(CAPTCHA_1_FORM_CLASS, field_key="class"):
                self._captcha_1_submit()
            elif self.last_response_parsed.find("input",
                                                id=lambda
                                                        value: value and value.startswith(
                                                    CAPTCHA_2_INPUT_ID)):
                self._captcha_2_submit()
            elif self._is_field_found(MFA_DEVICE_SELECT_FORM_ID,
                                      field_key="id"):
                self._mfa_device_select()
            elif self._is_field_found(MFA_FORM_ID, field_key="id"):
                self._mfa_submit()
            else:
                raise AmazonOrdersAuthError(
                    "An error occurred, this is an unknown page: {}. To capture the page to a file, set the `debug` flag.".format(
                        self.last_response.url))

            attempts += 1

        if attempts == self.max_auth_attempts:
            raise AmazonOrdersAuthError(
                "Max authentication flow attempts reached.")

    def logout(self) -> None:
        """
        Logout and close the existing Amazon session and clear cookies.
        """
        self.get("{}/gp/sign-out.html".format(BASE_URL))

        if os.path.exists(self.cookie_jar_path):
            os.remove(self.cookie_jar_path)

        self.session.close()
        self.session = Session()

        self.is_authenticated = False

    def _sign_in(self) -> None:
        form = self.last_response_parsed.find("form",
                                              {"name": SIGN_IN_FORM_NAME})
        data = self._build_from_form(form,
                                     additional_attrs={"email": self.username,
                                                       "password": self.password,
                                                       "rememberMe": "true"})

        self.request(form.attrs.get("method", "GET"),
                     self._get_form_action(form),
                     data=data)

        self._handle_errors(critical=True)

    def _mfa_device_select(self) -> None:
        form = self.last_response_parsed.find("form",
                                              {"id": MFA_DEVICE_SELECT_FORM_ID})
        contexts = form.find_all("input", {"name": "otpDeviceContext"})

        i = 1
        for field in contexts:
            self.io.echo("{}: {}".format(i, field.attrs["value"].strip()))
            i += 1
        otp_device = int(
            self.io.prompt("Enter where you would like your one-time passcode sent", type=int))

        form = self.last_response_parsed.find("form",
                                              id=MFA_DEVICE_SELECT_FORM_ID)
        data = self._build_from_form(form,
                                     additional_attrs={"otpDeviceContext":
                                                           contexts[
                                                               otp_device - 1].attrs[
                                                               "value"]})

        self.request(form.attrs.get("method", "GET"),
                     self._get_form_action(form),
                     data=data)

        self._handle_errors()

    def _mfa_submit(self) -> None:
        otp = self.io.prompt("Enter the one-time passcode sent to your device")

        form = self.last_response_parsed.find("form", id=MFA_FORM_ID)
        data = self._build_from_form(form,
                                     additional_attrs={"otpCode": otp,
                                                       "rememberDevice": ""})

        self.request(form.attrs.get("method", "GET"),
                     self._get_form_action(form),
                     data=data)

        self._handle_errors()

    def _captcha_1_submit(self) -> None:
        captcha_div = self.last_response_parsed.find("div",
                                                     {"id": CAPTCHA_1_DIV_ID})

        solution = self._solve_captcha(
            captcha_div.find("img", {"alt": "captcha"}).attrs["src"])

        form = self.last_response_parsed.find("form",
                                              {"class": CAPTCHA_1_FORM_CLASS})
        data = self._build_from_form(form,
                                     additional_attrs={
                                         "cvf_captcha_input": solution})

        self.request(form.attrs.get("method", "GET"),
                     self._get_form_action(form,
                                           prefix="{}/ap/cvf/".format(
                                               BASE_URL)),
                     data=data)

        self._handle_errors("cvf-widget-alert", "class")

    def _captcha_2_submit(self) -> None:
        form = self.last_response_parsed.find("input",
                                              id=lambda
                                                  value: value and value.startswith(
                                                  CAPTCHA_2_INPUT_ID)).find_parent(
            "form")

        solution = self._solve_captcha(form.find("img").attrs["src"])

        data = self._build_from_form(form,
                                     additional_attrs={
                                         "field-keywords": solution})

        self.request(form.attrs.get("method", "GET"),
                     self._get_form_action(form,
                                           prefix=BASE_URL),
                     params=data)

        self._handle_errors("a-alert-info", "class")

    def _build_from_form(self,
                         form: Tag,
                         additional_attrs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = {}
        for field in form.find_all("input"):
            try:
                data[field["name"]] = field["value"]
            except:
                pass
        if additional_attrs:
            data.update(additional_attrs)
        return data

    def _get_form_action(self,
                         form: Tag,
                         prefix: Optional[str] = None) -> str:
        action = form.attrs.get("action")
        if not action:
            action = self.last_response.url
        if prefix and not action.startswith("http"):
            action = prefix + action
        return action

    def _is_field_found(self,
                        field_value: str,
                        field_type: str = "form",
                        field_key: str = "name") -> bool:
        return self.last_response_parsed.find(field_type, {
            field_key: field_value}) is not None

    def _get_page_from_url(self,
                           url: str) -> str:
        page_name = os.path.basename(urlparse(url).path).strip(".html")
        i = 0
        while os.path.isfile("{}_{}".format(page_name, 0)):
            i += 1
        return "{}_{}.html".format(page_name, i)

    def _handle_errors(self,
                       error_div: str = "auth-error-message-box",
                       attr_name: str = "id",
                       critical: bool = False) -> None:
        error_div = self.last_response_parsed.find("div",
                                                   {attr_name: error_div})
        if error_div:
            error_msg = "An error occurred: {}".format(error_div.text.strip())

            if critical:
                raise AmazonOrdersAuthError(error_msg)
            else:
                self.io.echo(error_msg)

    def _solve_captcha(self,
                       url: str) -> str:
        captcha_response = AmazonCaptcha.fromlink(url).solve()
        if not captcha_response or captcha_response.lower() == "not solved":
            img_response = self.session.get(url)
            img = Image.open(BytesIO(img_response.content))
            img.show()
            self.io.echo("The Captcha couldn't be auto-solved.")
            captcha_response = self.io.prompt("Enter the characters shown in the image")

        return captcha_response
