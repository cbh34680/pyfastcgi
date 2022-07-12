<?php
$data = @$_POST['key1']
?>
<html>
    <head>
    </head>
    <body>
        <a href="/">python</a>
        <hr />
        <form method="POST" action="/php/post.php">
            <input type="text" name="key1" value="value1" />
            <br />
            <input type="submit" />
        </form>
        <hr />
        <pre><?php echo $data ?></pre>
    </body>
</html>