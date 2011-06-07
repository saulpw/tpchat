
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


function on_load()
{
    $("#chatline").focus()
    $("#f").submit(say)

    $(document).ajaxError(function (event, xhr, opts, err) { 
       if (opts.url == lasturl) {
           wait_for_chat(lastt);
       } else {
           error("remote", opts.url + " failed: <br/>status: " + xhr.statusText + "<br/> response: " + xhr.responseText + "<br/>event: " + event + "<br/>err: " + err)
       }
    })

    recvtimeout = setTimeout('wait_for_chat(0)', 10)
    sendtimer = setInterval('send_accum_text()', 200)
}

var lastt = 0;
var lasturl = "";
var tClientStarted = new Date();
var localOffset = tClientStarted.getTimezoneOffset() * 60000;

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

function post_new_chat(x)
{
    var newchat = $(x);

    $(".time", newchat).each(function (i, v) {
        var d = new Date($(v).text() * 1000 + localOffset);
        var t = getClockString(d);
        $(v).text(t);
    });

    $(".date", newchat).each(function (i, v) {
        var d = new Date($(v).text() * 1000 + localOffset);
        var t = getDateString(d);
        $(v).text(t);
    });

    $("#log").append(newchat.html());

    // scroll to bottom of log
    $("#log").scrollTop(999999);

    // for IE (does this assume 12px font height?)
    var h1 = $("#log").scrollTop();
    $("#log").scrollTop(h1*12);

}

function wait_for_chat(t)
{
    lastt = t;
    lasturl = "/log?t=" + t
    $.get(lasturl).success(function(x) {
          post_new_chat(x);
          var t1 = $(x).attr("t");
          if (!isFinite(t1)) t1 = t;
       	  wait_for_chat(t1);

          return true;
    }).error(function (x) {
        error("remote", lasturl + " failed")
    });
}

$(document).ready(on_load);

