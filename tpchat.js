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

    setTimeout('wait_for_chat(0)', 10)
    setInterval('send_accum_text()', 100)
}

var lastt = 0;
var lasturl = "";

function post_new_chat(x)
{
    $("#log").append($(x).html())

    // scroll to bottom of log
    $("#log").scrollTop(999999)

    // for IE (does this assume 12px font height?)
    var h1 = $("#log").scrollTop()
    $("#log").scrollTop(h1*12)
}

function wait_for_chat(t)
{
    var d = new Date()
    var gmtHours = -d.getTimezoneOffset()/60 
    lastt = t;
    lasturl = "/log?tz=" + gmtHours + "&t=" + t
    $.get(lasturl, function(x) {
          post_new_chat(x);
          var t1 = $(x).attr("t");
          if (!isFinite(t1)) t1 = t;
       	  wait_for_chat(t1);

          return true;
    });
}


$(document).ready(on_load)


