var title_string = "emups";

var reconnectTimeout = 250;
var nRetries = 0;
var maxRetries = 6;

var num_new_messages = 0;

var text_sending = "";
var text_to_send = "";

var sendtimer = null;

function replaceMacros(s) {
    return s;
}

function warnColor(n)
{
    var color = "#FFFFFF";
    switch (n) {
    case -6: color = "#0000FF"; break;
    case -5: color = "#4444FF"; break;
    case -4: color = "#7777FF"; break;
    case -3: color = "#9999FF"; break;
    case -2: color = "#BBBBFF"; break;
    case -1: color = "#DDDDFF"; break;
    case 0: color = "#FFFFFF"; break;
    case 1: color = "#DDFFDD"; break;
    case 2: color = "#BBFFBB"; break;
    case 3: color = "#99FF99"; break;
    case 4: color = "#77FF77"; break;
    case 5: color = "#44FF44"; break;
    default: color = "#C7DE6A"; break;
    }
    $(".msgs").css("background-color", color);
}

function error(t, e)
{
   $("#error #" + t).html(e)

    warnColor(nRetries);

    if (nRetries < maxRetries) {
        set_wait_timer(reconnectTimeout);
    } else {
        $(".msgs").addClass("disconnected");
    }
}

function say(e)
{
   e.preventDefault();
   var v = $("#chatline").val();
   if (v != "") {
      text_to_send += replaceMacros(v) + "\n";
      $("#chatline").val('');
   }
  
   clearTimeout(sendtimer);
   sendtimer = setTimeout('send_accum_text()', 50);

   setTimeout(function() { $("#chatline").focus(); }, 10);

   return false;
}

function send_accum_text()
{
    if (text_sending != "") {
        error("local", "not ready to send '" + text_to_send + "'!  ");
        return;
    }

    if (text_to_send == "") {
        return;
    }

   text_sending += text_to_send;
   text_to_send = "";

   $.ajax({ type: 'POST',
            url: '/log',
            data: { chatline: text_sending },
            success: function (data, stat, xhr) {
              text_sending = "";
            },
            complete: function (xhr, stat) { 
              if (text_sending != "") {  // not successful
                 text_to_send = text_sending + text_to_send;  // send next time
                 text_sending = "";
              }

              if (text_to_send != "") {
                 clearTimeout(sendtimer);
                 sendtimer = setTimeout('send_accum_text()', 50);
              }
            }
          })
}


function on_load()
{
    var w = $("body")
    w.isFocused = true;
    w.focusin(function () {
            window.isFocused = true;
            num_new_messages = 0;
            set_title();
    });
    w.focusout(function () {
            window.isFocused = false;
    });

    $("#chatline").focus();
    $("#f").submit(say);

    set_wait_timer(1); // first time do it right away

    var nickname = $("#b").text();
    setCookie("nickname", nickname, 365*24);
}

var lastt = -1;
var lasturl = "";
var tClientStarted = new Date();
var recvtimeout = undefined;
var cacheblocker = tClientStarted.getTime();

function set_wait_timer(timeout)
{
    clearTimeout(recvtimeout);
    recvtimeout = setTimeout('wait_for_chat(lastt)', timeout)
}

function getClockString(d)
{
    var h = d.getHours();
    var m = d.getMinutes();
    if (h < 10) h = "0" + h;
    if (m < 10) m = "0" + m;
    return h + ":" + m;
}

function getDateString(d)
{
    return d.toLocaleDateString();
}

function post_new_chat(x, replace)
{
    var newchat = $(x);

    $(".time", newchat).each(function (i, v) {
        var timet = $(v).attr("timet");
        var d = new Date(timet * 1000);
        var t = getClockString(d);
        $(v).text(t);
    });

    $(".stardate", newchat).each(function (i, v) {
        var timet = $(v).attr("timet");
        var d = new Date(timet * 1000);
        var t = getDateString(d);
        $(v).html(t);
    });

    if (replace) {
        $("#log").html(newchat.html());
    } else {
        $("#log").append(newchat.html());

        // scroll to bottom of log
        $("#log").scrollTop(999999);

        // for IE (does this assume 12px font height?)
        var h1 = $("#log").scrollTop();
        $("#log").scrollTop(h1*12);
    }

    if (! window.isFocused) {
        num_new_messages += 1;
        set_title();
    }
}

function set_title() {
    var prefix = "";
    if (num_new_messages > 0) {
        prefix = "(" + num_new_messages + ") ";
    }
    document.title = prefix + title_string;
}

function get_backlog(ttt)
{
    $.get("/log?t=-" + ttt).success(function(x) {
        post_new_chat(x, true);
        return true;
    }).error(function (x) {
        nRetries -= 1;
        warnColor(nRetries);
    });
}

function wait_for_chat(t)
{
    lastt = t;
    lasturl = "/log?t=" + lastt + "&cb=" + cacheblocker;
    cacheblocker += 1;

    $.get(lasturl).success(function(x) {
        post_new_chat(x, false);
        var t1 = parseInt($(x).attr("nextt"));
        if (!isFinite(t1)) { // logged out
            lastt = -1;
            nRetries = maxRetries;
            error("remote", "invalid nextt");
            return;
        }
        nRetries = 0;
        warnColor(nRetries);
        wait_for_chat(t1);

        return true;
    }).error(function (event, xhr, opts, err) {
        set_wait_timer(reconnectTimeout);
    });
}

// ----  helpers
function setCookie(name,value,hours) {
    if (hours) {
        var date = new Date();
        date.setTime(date.getTime()+(hours*60*60*1000));
        var expires = "; expires="+date.toGMTString();
    }
    else var expires = "";
    document.cookie = name+"="+value+expires+"; path=/";
}


$(document).ready(on_load);

