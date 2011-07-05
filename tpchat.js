
var send_text = "";
var ready_to_send = true;

function error(t, e)
{
   $("#error #" + t).html(e)
}

function say(e)
{
   e.preventDefault();
   var v = $("#chatline").val();
   if (v != "") {
      send_text += v + "\n";
      $("#chatline").val('');
   }
   return false;
}

function send_accum_text()
{
   if (send_text != "") {
       if (!ready_to_send) {
          error("local", "not ready to send '<pre>" + send_text + "'</pre>!  ");
          return;
       }
       ready_to_send = false;
       $.ajax({ type: 'POST',
                url: '/log',
                data: { chatline: send_text },
                success: function (data, stat, xhr) {
                  send_text = "";
                },
                complete: function (xhr, stat) { 
                  if (send_text != "") {
                     $("#chatline").val(send_text + "\n" + $("#chatline").val());
                     send_text = "";
                  } 
                  ready_to_send = true; 
                },
                error: function (xhr, status, err) {
                    error("remote", status);
                    clearInterval(sendtimer);
                    sendtimer = setInterval('send_accum_text()', 2000);
                }
              })
   }
}

var reconnectTimeout = 100;

function wait_error(event, xhr, opts, err)
{
    msg = opts.url + " failed: ";
    msg += "<br/>status: " + xhr.statusText;
    msg += "<br/>response: " + xhr.responseText;
    msg += "<br/>event: " + event;
    msg += "<br/>error: " + err;

    error("remote", msg);
    $(".msgs").addClass("disconnected");
}

function on_load()
{
    $("#chatline").focus();
    $("#f").submit(say);

    $(document).ajaxError(wait_error);

    set_wait_timer();
    sendtimer = setInterval('send_accum_text()', 200)
}

var lastt = -1;
var lasturl = "";
var tClientStarted = new Date();
var localOffset = tClientStarted.getTimezoneOffset() * 60000;
var recvtimeout = undefined;

function set_wait_timer()
{
    clearTimeout(recvtimeout);
    recvtimeout = setTimeout('wait_for_chat(lastt)', reconnectTimeout)
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
        var d = new Date($(v).attr("timet") * 1000 + localOffset);
        var t = getClockString(d);
        $(v).text(t);
    });

    $(".date", newchat).each(function (i, v) {
        var d = new Date($(v).attr("timet") * 1000 + localOffset);
        var t = getDateString(d); // + " &#x2B06;";
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
}

function get_backlog(ttt)
{
    $.get("/log?t=-" + ttt).success(function(x) {
          post_new_chat(x, true);
          return true;
    });
}

function wait_for_chat(t)
{
    lastt = t;
    lasturl = "/log?t=" + lastt;

    $.get(lasturl).success(function(x) {
        post_new_chat(x, false);
        var t1 = parseInt($(x).attr("nextt"));
        if (!isFinite(t1)) {
            lastt = -1;
            error("remote", "invalid nextt");
            return;
        }
        wait_for_chat(t1);

        return true;
    });
}

$(document).ready(on_load);

